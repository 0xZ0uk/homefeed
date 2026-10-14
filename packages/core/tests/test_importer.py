import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import curation
from homefeed_core.candidates import list_candidates
from homefeed_core.db import open_database
from homefeed_core.importer import TAKEOUT, ImportReport, TakeoutFormatError, import_takeout
from homefeed_core.ratings import set_rating

FIXTURES = Path(__file__).parent / "fixtures" / "takeout"
SPACE = "UCspaceexplained00000001"
CHILL = "UCchillchannel0000000001"
T0 = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def run_import(
    sessions: sessionmaker[Session], file: bytes | str, **kwargs: object
) -> ImportReport:
    with sessions.begin() as session:
        return import_takeout(session, file, now=T0, **kwargs)  # pyright: ignore[reportArgumentType]


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.mark.parametrize("name", ["watch-history.json", "watch-history.html"])
def test_counts_every_entry_in_one_bucket(sessions: sessionmaker[Session], name: str) -> None:
    report = run_import(sessions, fixture(name))

    assert report.format == name.rsplit(".", 1)[1]
    assert report.watches == 5
    assert report.removed == 2  # removed video, and a private one without its channel
    assert report.skipped == 2  # an ad, and a survey answer (JSON) or a search (HTML)
    assert report.malformed == (5 if report.format == "json" else 3)
    assert report.entries == (report.watches + report.removed + report.skipped + report.malformed)
    assert report.videos == 4
    assert report.channels == 2
    assert report.new_videos == 4
    assert report.new_channels == 2
    assert report.new_candidates == 4
    assert report.subscribed == []
    assert report.oldest_watch_at == "2026-09-01T08:00:00.000Z"


def test_json_reads_times_exactly(sessions: sessionmaker[Session]) -> None:
    report = run_import(sessions, fixture("watch-history.json"))

    assert report.entries == 14
    assert report.newest_watch_at == "2026-10-10T20:15:02.123Z"


def test_html_reads_times_with_offsets_and_names_zones_as_utc(
    sessions: sessionmaker[Session],
) -> None:
    report = run_import(sessions, fixture("watch-history.html"))

    assert report.entries == 12
    # "10:15:02 PM CEST" (with a narrow no-break space): zone names are read as UTC.
    assert report.newest_watch_at == "2026-10-10T22:15:02.000Z"


@pytest.mark.parametrize("name", ["watch-history.json", "watch-history.html"])
def test_seeds_channels_videos_and_candidates(sessions: sessionmaker[Session], name: str) -> None:
    run_import(sessions, fixture(name))

    with sessions() as session:
        channels = {r.id: r.title for r in session.execute(text("SELECT id, title FROM channels"))}
        rows = list(session.execute(text("SELECT id, channel_id, title FROM videos")))
        videos = {row.id: row.channel_id for row in rows}
        titles = {row.id: row.title for row in rows}
        pool = list_candidates(session)

    assert channels == {SPACE: "Space Explained", CHILL: "Chill Channel"}
    assert videos == {
        "rocket00001": SPACE,
        "orbital0002": SPACE,
        "lofibeats01": CHILL,
        "launch00001": SPACE,
    }
    assert titles["rocket00001"] == "How rockets work"
    assert {c.video_id for c in pool} == set(videos)
    assert {c.source for c in pool} == {TAKEOUT}
    assert all(c.first_seen_at == "2026-10-12T06:00:00.000Z" for c in pool)


def test_html_titles_unescape_entities(sessions: sessionmaker[Session]) -> None:
    run_import(sessions, fixture("watch-history.html"))

    with sessions() as session:
        title = session.execute(text("SELECT title FROM videos WHERE id = 'orbital0002'"))
        assert title.scalar_one() == "Orbital mechanics, part 2 & more"


@pytest.mark.parametrize("name", ["watch-history.json", "watch-history.html"])
def test_never_creates_ratings_or_watch_events(sessions: sessionmaker[Session], name: str) -> None:
    run_import(sessions, fixture(name), subscribe_min_watches=1)

    with sessions() as session:
        assert session.execute(text("SELECT count(*) FROM ratings")).scalar_one() == 0
        assert session.execute(text("SELECT count(*) FROM watch_events")).scalar_one() == 0


def test_ads_are_not_imported(sessions: sessionmaker[Session]) -> None:
    run_import(sessions, fixture("watch-history.json"))

    with sessions() as session:
        ad = session.execute(text("SELECT count(*) FROM videos WHERE id = 'advert00001'"))
        assert ad.scalar_one() == 0


def test_subscribes_to_channels_watched_often_enough(sessions: sessionmaker[Session]) -> None:
    report = run_import(sessions, fixture("watch-history.json"), subscribe_min_watches=2)

    assert report.subscribed == [SPACE]
    with sessions() as session:
        assert curation.subscribed_channel_ids(session) == [SPACE]
        subscription = curation.get_channel(session, SPACE)
    assert subscription is not None
    assert subscription.prior == "neutral"


def test_subscribing_keeps_existing_preferences(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, 'Mine')"), {"id": SPACE}
        )
        session.execute(
            text("INSERT INTO channel_prefs (channel_id, prior, pinned) VALUES (:id, 'love', 1)"),
            {"id": SPACE},
        )

    report = run_import(sessions, fixture("watch-history.json"), subscribe_min_watches=1)

    assert report.subscribed == [CHILL]
    assert report.new_channels == 1
    with sessions() as session:
        subscription = curation.get_channel(session, SPACE)
    assert subscription is not None
    assert (subscription.title, subscription.prior, subscription.pinned) == ("Mine", "love", True)


def test_keeps_stored_videos_and_skips_rated_ones(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        session.execute(text("INSERT INTO channels (id, title) VALUES (:id, 'S')"), {"id": SPACE})
        session.execute(
            text(
                "INSERT INTO videos (id, channel_id, title, duration_seconds) "
                "VALUES ('rocket00001', :channel, 'Rockets, enriched', 600)"
            ),
            {"channel": SPACE},
        )
        set_rating(session, "rocket00001", 8)

    report = run_import(sessions, fixture("watch-history.json"))

    assert report.new_videos == 3
    assert report.new_candidates == 3
    with sessions() as session:
        title = session.execute(text("SELECT title FROM videos WHERE id = 'rocket00001'"))
        assert title.scalar_one() == "Rockets, enriched"
        assert "rocket00001" not in {c.video_id for c in list_candidates(session)}
        assert session.execute(text("SELECT count(*) FROM ratings")).scalar_one() == 1


def test_caps_candidates_to_the_most_recent_watches(sessions: sessionmaker[Session]) -> None:
    report = run_import(sessions, fixture("watch-history.json"), max_candidates=2)

    assert report.new_candidates == 2
    assert report.new_videos == 4
    with sessions() as session:
        assert {c.video_id for c in list_candidates(session)} == {"rocket00001", "orbital0002"}


def test_importing_again_adds_nothing_new(sessions: sessionmaker[Session]) -> None:
    run_import(sessions, fixture("watch-history.json"), subscribe_min_watches=1)
    again = run_import(sessions, fixture("watch-history.html"), subscribe_min_watches=1)

    assert again.watches == 5
    assert (again.new_videos, again.new_channels, again.new_candidates) == (0, 0, 0)
    assert again.subscribed == []


def test_accepts_text_file_objects_and_a_byte_order_mark(sessions: sessionmaker[Session]) -> None:
    content = "﻿" + fixture("watch-history.json").decode()
    with sessions.begin() as session:
        report = import_takeout(session, io.BytesIO(content.encode()))
    assert report.watches == 5
    assert run_import(sessions, content).watches == 5


def test_empty_json_history_imports_nothing(sessions: sessionmaker[Session]) -> None:
    report = run_import(sessions, b"[]")

    assert (report.entries, report.watches, report.newest_watch_at) == (0, 0, None)


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"just some text",
        b"[{broken json",
        json.dumps({"title": "not a list"}).encode(),
        b"<html><body><p>Not a takeout page</p></body></html>",
        b"\xff\xfe\x00garbage",
    ],
)
def test_rejects_files_that_are_not_a_watch_history(
    sessions: sessionmaker[Session], content: bytes
) -> None:
    with pytest.raises(TakeoutFormatError), sessions.begin() as session:
        import_takeout(session, content)


def test_rejects_invalid_options(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(ValueError), sessions.begin() as session:
        import_takeout(session, b"[]", subscribe_min_watches=0)
    with pytest.raises(ValueError), sessions.begin() as session:
        import_takeout(session, b"[]", max_candidates=-1)
