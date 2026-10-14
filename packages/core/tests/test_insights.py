import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import open_database
from homefeed_core.insights import (
    RatedVideo,
    ScoreShare,
    ShownItem,
    summarize_weeks,
    week_start,
    weekly_insights,
)

MONDAY = date(2026, 10, 5)
NEXT_MONDAY = date(2026, 10, 12)
# Wednesday of the second week.
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
CHANNEL = "UC" + "c" * 22


def shown(
    video_id: str,
    day: date,
    *,
    model: float = 0.0,
    curation: float = 0.0,
    similarity: float = 0.0,
    rated: bool = False,
) -> ShownItem:
    return ShownItem(video_id, day, model, curation, similarity, rated)


def shares(share: ScoreShare | None) -> tuple[float, float, float]:
    assert share is not None
    return (share.model, share.curation, share.similarity)


def test_week_start_is_monday() -> None:
    assert week_start(date(2026, 10, 11)) == MONDAY  # Sunday
    assert week_start(MONDAY) == MONDAY
    assert week_start(NEXT_MONDAY) == NEXT_MONDAY


def test_empty_weeks_have_no_rates() -> None:
    [week] = summarize_weeks([], [], first_week=MONDAY, weeks=1)

    assert week.week_start == MONDAY
    assert week.rated_count == 0
    assert week.good_rate is None
    assert week.rating_rate is None
    assert week.score_share is None
    assert week.feed_count == 0
    assert [c.score for c in week.score_counts] == list(range(10, 0, -1))
    assert [c.count for c in week.score_counts] == [0] * 10


def test_good_rate_counts_6_and_up() -> None:
    ratings = [
        RatedVideo("a", 6, MONDAY),
        RatedVideo("b", 10, date(2026, 10, 11)),
        RatedVideo("c", 5, MONDAY),
        RatedVideo("d", 1, date(2026, 10, 8)),
        RatedVideo("e", 8, NEXT_MONDAY),
    ]

    first, second = summarize_weeks(ratings, [], first_week=MONDAY, weeks=2)

    assert (first.rated_count, first.good_count, first.good_rate) == (4, 2, 0.5)
    counts = {c.score: c.count for c in first.score_counts}
    assert counts == {10: 1, 9: 0, 8: 0, 7: 0, 6: 1, 5: 1, 4: 0, 3: 0, 2: 0, 1: 1}
    assert (second.rated_count, second.good_rate) == (1, 1.0)


def test_ratings_outside_the_weeks_are_ignored() -> None:
    ratings = [RatedVideo("a", 2, date(2026, 10, 4)), RatedVideo("b", 9, date(2026, 10, 19))]

    [week] = summarize_weeks(ratings, [], first_week=MONDAY, weeks=1)

    assert week.rated_count == 0


def test_rating_rate_counts_distinct_shown_videos() -> None:
    items = [
        shown("a", MONDAY, rated=True),
        shown("a", date(2026, 10, 6), rated=True),  # shown again: still one video
        shown("b", MONDAY),
        shown("c", date(2026, 10, 6)),
        shown("d", date(2026, 10, 6), rated=True),
    ]

    [week] = summarize_weeks([], items, first_week=MONDAY, weeks=1)

    assert (week.shown_count, week.shown_rated_count, week.rating_rate) == (4, 2, 0.5)
    assert week.feed_count == 2


def test_score_share_is_split_by_absolute_contribution() -> None:
    items = [
        shown("a", MONDAY, curation=0.6, similarity=0.2),
        shown("b", date(2026, 10, 6), model=0.4, curation=0.6, similarity=0.2),
    ]

    [week] = summarize_weeks([], items, first_week=MONDAY, weeks=1)

    assert shares(week.score_share) == pytest.approx((0.2, 0.6, 0.2))
    assert (week.feed_count, week.model_feed_count) == (2, 1)


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    with factory.begin() as session:
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, 'Channel')"), {"id": CHANNEL}
        )
        for n in range(4):
            session.execute(
                text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :c, 'Video')"),
                {"id": vid(n), "c": CHANNEL},
            )
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def vid(n: int) -> str:
    return f"v{n:010d}"


def add_feed(
    session: Session, day: date, created_at: str, items: list[tuple[str, dict[str, object]]]
) -> None:
    feed_id = session.execute(
        text("INSERT INTO feeds (date, created_at) VALUES (:date, :at) RETURNING id"),
        {"date": day.isoformat(), "at": created_at},
    ).scalar_one()
    for position, (video_id, breakdown) in enumerate(items):
        session.execute(
            text(
                """
                INSERT INTO feed_items (feed_id, video_id, position, source, score,
                                        breakdown, explanation)
                VALUES (:feed, :video, :position, 'subscription', 0, :breakdown, '')
                """
            ),
            {
                "feed": feed_id,
                "video": video_id,
                "position": position,
                "breakdown": json.dumps(breakdown),
            },
        )


def rate(session: Session, video_id: str, score: int, rated_at: str) -> None:
    session.execute(
        text("INSERT INTO ratings (video_id, score, value, rated_at) VALUES (:v, :s, 0, :at)"),
        {"v": video_id, "s": score, "at": rated_at},
    )


def test_weekly_insights_reads_ratings_and_the_feed_of_record(
    sessions: sessionmaker[Session],
) -> None:
    rules = {"model": 0.0, "alpha": 0.0, "channel": 0.25, "topics": {"wood": -0.25}}
    blended = {
        "model": 0.5,
        "alpha": 0.5,
        "channel": 0.25,
        "similarity": -0.25,
        "tags": {},
    }
    with sessions.begin() as session:
        # Superseded by the refresh later that day; not the feed of record.
        add_feed(session, NEXT_MONDAY, "2026-10-12T05:00:00.000Z", [(vid(3), rules)])
        add_feed(
            session,
            NEXT_MONDAY,
            "2026-10-12T09:00:00.000Z",
            [(vid(0), rules), (vid(1), blended)],
        )
        add_feed(session, MONDAY, "2026-10-05T05:00:00.000Z", [(vid(2), rules)])
        rate(session, vid(0), 8, "2026-10-13T10:00:00.000Z")
        rate(session, vid(2), 5, "2026-10-06T10:00:00.000Z")
        rate(session, vid(3), 6, "2026-09-01T10:00:00.000Z")  # before the window

    with sessions.begin() as session:
        first, second = weekly_insights(session, weeks=2, now=NOW, tz=UTC)

    assert first.week_start == MONDAY
    assert (first.rated_count, first.good_rate) == (1, 0.0)
    assert (first.shown_count, first.rating_rate) == (1, 1.0)
    assert first.score_share == ScoreShare(model=0.0, curation=1.0, similarity=0.0)
    assert first.model_feed_count == 0

    assert second.week_start == NEXT_MONDAY
    assert (second.rated_count, second.good_rate) == (1, 1.0)
    assert (second.shown_count, second.shown_rated_count) == (2, 1)
    # |0.25| + |-0.25| curation; then |0.25| model, |0.25| curation, |-0.25| similarity.
    assert shares(second.score_share) == pytest.approx((0.2, 0.6, 0.2))
    assert (second.feed_count, second.model_feed_count) == (1, 1)


def test_weekly_insights_puts_ratings_in_local_weeks(sessions: sessionmaker[Session]) -> None:
    from zoneinfo import ZoneInfo

    with sessions.begin() as session:
        # Sunday 23:30 UTC is already Monday in Lisbon summer time (UTC+1).
        rate(session, vid(0), 9, "2026-10-11T23:30:00.000Z")

    with sessions.begin() as session:
        utc = weekly_insights(session, weeks=2, now=NOW, tz=UTC)
        lisbon = weekly_insights(session, weeks=2, now=NOW, tz=ZoneInfo("Europe/Lisbon"))

    assert [w.rated_count for w in utc] == [1, 0]
    assert [w.rated_count for w in lisbon] == [0, 1]


def test_weekly_insights_rejects_bad_week_counts(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session, pytest.raises(ValueError):
        weekly_insights(session, weeks=0)
