from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.candidates import SAVED_SEARCH, Candidate, default_sources, generate
from homefeed_core.candidates import list_candidates as pool
from homefeed_core.db import open_database
from homefeed_core.gateway import RateLimitedError, SearchFilters
from homefeed_core.gateway.fake import FakeGateway, make_channel, make_video
from homefeed_core.ratings import set_rating
from homefeed_core.saved_searches import (
    DuplicateSavedSearchError,
    SavedSearchSource,
    add_saved_search,
    decode_filters,
    delete_saved_search,
    due_saved_searches,
    encode_filters,
    get_saved_search,
    list_saved_searches,
    record_run,
    update_saved_search,
)

T0 = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
NEWEST = SearchFilters(sort="upload_date", upload_date="week")
WOOD = make_channel("UC" + "w" * 22, title="Wood", handle="@wood")
METAL = make_channel("UC" + "m" * 22, title="Metal")


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def save(
    sessions: sessionmaker[Session], query: str, filters: SearchFilters | None = None, **kw: str
) -> int:
    with sessions.begin() as session:
        search, created = add_saved_search(session, query, filters, **kw)  # type: ignore[arg-type]
    assert created
    return search.id


def set_last_run(sessions: sessionmaker[Session], search_id: int, at: datetime) -> None:
    with sessions.begin() as session:
        record_run(session, search_id, found_count=0, now=at)


# Persistence


def test_filters_round_trip_as_canonical_json() -> None:
    assert encode_filters(SearchFilters()) == "{}"
    assert encode_filters(NEWEST) == '{"sort":"upload_date","upload_date":"week"}'
    assert decode_filters(encode_filters(NEWEST)) == NEWEST
    assert decode_filters('{"duration":"long","unknown":1}') == SearchFilters(duration="long")


def test_add_and_list(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        wood, created = add_saved_search(session, "  woodworking   joints ", NEWEST)
        add_saved_search(session, "Blacksmithing", schedule="weekly")

    assert created
    assert (wood.query, wood.filters, wood.schedule) == ("woodworking joints", NEWEST, "daily")
    assert (wood.last_run_at, wood.last_found_count, wood.last_error) == (None, None, None)
    assert wood.next_run_at == wood.created_at  # never ran: due now
    with sessions() as session:
        searches = list_saved_searches(session)
    assert [(s.query, s.schedule) for s in searches] == [
        ("Blacksmithing", "weekly"),
        ("woodworking joints", "daily"),
    ]


def test_saving_again_returns_the_existing_search(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        first, _ = add_saved_search(session, "Woodworking", NEWEST)
        again, created = add_saved_search(session, "WOODWORKING", NEWEST, schedule="weekly")
        other_filters, other_created = add_saved_search(session, "woodworking")

    assert not created
    assert again == first
    assert other_created and other_filters.id != first.id


@pytest.mark.parametrize("query", ["", "   ", "x" * 201])
def test_add_rejects_blank_and_long_queries(sessions: sessionmaker[Session], query: str) -> None:
    with sessions.begin() as session, pytest.raises(ValueError):
        add_saved_search(session, query)


def test_add_rejects_unknown_schedules(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session, pytest.raises(ValueError, match="Schedule"):
        add_saved_search(session, "wood", schedule="hourly")  # type: ignore[arg-type]


def test_update_schedule_keeps_the_last_run(sessions: sessionmaker[Session]) -> None:
    search_id = save(sessions, "wood")
    set_last_run(sessions, search_id, T0)

    with sessions.begin() as session:
        updated = update_saved_search(session, search_id, schedule="weekly")

    assert updated is not None
    assert (updated.schedule, updated.last_run_at) == ("weekly", "2026-10-12T06:00:00.000Z")
    assert updated.next_run_at == "2026-10-19T06:00:00.000Z"


def test_update_query_or_filters_makes_the_search_due_again(
    sessions: sessionmaker[Session],
) -> None:
    search_id = save(sessions, "wood")
    set_last_run(sessions, search_id, T0)

    with sessions.begin() as session:
        renamed = update_saved_search(session, search_id, query=" hand  tools ")
    set_last_run(sessions, search_id, T0)
    with sessions.begin() as session:
        refiltered = update_saved_search(session, search_id, filters=NEWEST)

    assert renamed is not None and refiltered is not None
    assert (renamed.query, renamed.last_run_at) == ("hand tools", None)
    assert (refiltered.query, refiltered.filters, refiltered.last_run_at) == (
        "hand tools",
        NEWEST,
        None,
    )


def test_update_pause(sessions: sessionmaker[Session]) -> None:
    search_id = save(sessions, "wood")

    with sessions.begin() as session:
        paused = update_saved_search(session, search_id, schedule="paused")

    assert paused is not None
    assert (paused.schedule, paused.next_run_at) == ("paused", None)


def test_update_rejects_duplicates_and_reports_missing(sessions: sessionmaker[Session]) -> None:
    save(sessions, "wood", NEWEST)
    search_id = save(sessions, "metal", NEWEST)

    with sessions.begin() as session:
        with pytest.raises(DuplicateSavedSearchError):
            update_saved_search(session, search_id, query="WOOD")
        assert update_saved_search(session, search_id, filters=SearchFilters()) is not None
        assert update_saved_search(session, 999, schedule="paused") is None
        with pytest.raises(ValueError):
            update_saved_search(session, search_id, query=" ")


def test_delete(sessions: sessionmaker[Session]) -> None:
    search_id = save(sessions, "wood")

    with sessions.begin() as session:
        assert delete_saved_search(session, search_id)
        assert not delete_saved_search(session, search_id)
        assert get_saved_search(session, search_id) is None


def test_record_run_keeps_the_last_count_on_failure(sessions: sessionmaker[Session]) -> None:
    search_id = save(sessions, "wood")

    with sessions.begin() as session:
        record_run(session, search_id, found_count=7, now=T0)
        record_run(session, search_id, error="rate limited", now=T0 + timedelta(days=1))
        search = get_saved_search(session, search_id)

    assert search is not None
    assert (search.last_found_count, search.last_error) == (7, "rate limited")
    assert search.last_run_at == "2026-10-13T06:00:00.000Z"


# Schedule


def test_due_saved_searches(sessions: sessionmaker[Session]) -> None:
    never = save(sessions, "never ran")
    daily = save(sessions, "daily")
    early = save(sessions, "daily, ran a little later yesterday")
    recent = save(sessions, "daily, ran recently")
    weekly = save(sessions, "weekly", schedule="weekly")
    weekly_recent = save(sessions, "weekly, ran recently", schedule="weekly")
    save(sessions, "paused", schedule="paused")
    set_last_run(sessions, daily, T0 - timedelta(days=1))
    set_last_run(sessions, early, T0 - timedelta(days=1) + timedelta(minutes=30))
    set_last_run(sessions, recent, T0 - timedelta(hours=12))
    set_last_run(sessions, weekly, T0 - timedelta(days=7))
    set_last_run(sessions, weekly_recent, T0 - timedelta(days=3))

    with sessions() as session:
        due = due_saved_searches(session, now=T0)

    # Never-run searches first, then the longest since their last run.
    assert [search.id for search in due] == [never, weekly, daily, early]


# Candidate source


def gateway_with_results() -> FakeGateway:
    gateway = FakeGateway()
    gateway.add_search(
        "woodworking",
        [
            make_video("aaaaaaaaaaa", channel=WOOD, title="Dovetails", view_count=1200),
            make_video("bbbbbbbbbbb", channel=WOOD),
        ],
    )
    gateway.add_search("metalwork", [make_video("ccccccccccc", channel=METAL)])
    return gateway


def test_source_records_results_with_attribution(sessions: sessionmaker[Session]) -> None:
    gateway = gateway_with_results()
    wood = save(sessions, "woodworking", NEWEST)
    save(sessions, "metalwork")

    report = generate([SavedSearchSource(sessions, gateway, now=T0)], sessions=sessions, now=T0)

    assert report.new == {SAVED_SEARCH: ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]}
    assert gateway.searches == [("woodworking", NEWEST), ("metalwork", SearchFilters())]
    with sessions() as session:
        assert pool(session) == [
            Candidate(video_id, SAVED_SEARCH, query, "2026-10-12T06:00:00.000Z")
            for video_id, query in [
                ("aaaaaaaaaaa", "woodworking"),
                ("bbbbbbbbbbb", "woodworking"),
                ("ccccccccccc", "metalwork"),
            ]
        ]
        stored = session.execute(
            text("SELECT title, view_count FROM videos WHERE id = 'aaaaaaaaaaa'")
        ).one()
        search = get_saved_search(session, wood)
    assert tuple(stored) == ("Dovetails", 1200)
    assert search is not None
    assert (search.last_run_at, search.last_found_count) == ("2026-10-12T06:00:00.000Z", 2)


def test_source_only_runs_due_searches(sessions: sessionmaker[Session]) -> None:
    gateway = gateway_with_results()
    save(sessions, "woodworking")
    save(sessions, "metalwork", schedule="paused")

    SavedSearchSource(sessions, gateway, now=T0).fetch()
    SavedSearchSource(sessions, gateway, now=T0 + timedelta(hours=12)).fetch()
    SavedSearchSource(sessions, gateway, now=T0 + timedelta(days=1)).fetch()

    assert [query for query, _ in gateway.searches] == ["woodworking", "woodworking"]


def test_source_limits_results_and_skips_rated_videos(sessions: sessionmaker[Session]) -> None:
    gateway = gateway_with_results()
    save(sessions, "woodworking")
    with sessions.begin() as session:
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, 'Wood')"), {"id": WOOD.id}
        )
        session.execute(
            text("INSERT INTO videos (id, channel_id, title) VALUES ('aaaaaaaaaaa', :c, 'A')"),
            {"c": WOOD.id},
        )
        set_rating(session, "aaaaaaaaaaa", 7.8)

    everything = SavedSearchSource(sessions, gateway, now=T0).fetch()
    with sessions.begin() as session:
        session.execute(text("UPDATE saved_searches SET last_run_at = NULL"))
    first_only = SavedSearchSource(sessions, gateway, per_search=1, now=T0).fetch()

    assert [video.video_id for video in everything] == ["bbbbbbbbbbb"]
    assert first_only == []  # its only result was rated


def test_one_failing_search_does_not_fail_the_others(sessions: sessionmaker[Session]) -> None:
    gateway = gateway_with_results()
    gateway.fail("search", "woodworking", RateLimitedError("HTTP Error 429"))
    wood = save(sessions, "woodworking")
    save(sessions, "metalwork")

    found = SavedSearchSource(sessions, gateway, now=T0).fetch()

    assert [video.video_id for video in found] == ["ccccccccccc"]
    with sessions() as session:
        search = get_saved_search(session, wood)
    assert search is not None
    assert (search.last_run_at, search.last_error) == ("2026-10-12T06:00:00.000Z", "HTTP Error 429")


def test_source_fails_when_every_search_failed(sessions: sessionmaker[Session]) -> None:
    gateway = gateway_with_results()
    gateway.fail("search", "woodworking", RateLimitedError("HTTP Error 429"))
    save(sessions, "woodworking")

    report = generate([SavedSearchSource(sessions, gateway, now=T0)], sessions=sessions)

    assert report.failed == {SAVED_SEARCH: "HTTP Error 429"}


def test_source_with_nothing_due_finds_nothing(sessions: sessionmaker[Session]) -> None:
    gateway = gateway_with_results()

    assert SavedSearchSource(sessions, gateway, now=T0).fetch() == []
    assert gateway.searches == []


def test_default_sources_include_saved_searches(sessions: sessionmaker[Session]) -> None:
    assert SAVED_SEARCH in [source.name for source in default_sources(sessions)]
