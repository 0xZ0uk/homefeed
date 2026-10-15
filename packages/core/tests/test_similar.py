import math
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.candidates import RELATED, SUBSCRIPTION, record
from homefeed_core.channel_hides import hide
from homefeed_core.config import Settings
from homefeed_core.curation import add_keyword_mute, subscribe_tag, update_tag_subscription
from homefeed_core.db import open_database
from homefeed_core.embeddings import EMBEDDING_DIMENSIONS, store_embedding
from homefeed_core.ratings import set_rating
from homefeed_core.similar import (
    RELATED_REASON,
    SIMILAR_REASON,
    SimilarVideo,
    similar_videos,
)
from homefeed_core.tags import ProposedTag, set_llm_tags
from homefeed_core.user_settings import update_user_settings
from homefeed_core.watch_events import record_watch_event

# Pinned, so the tests don't depend on the embedding model in the environment.
SETTINGS = Settings(similarity_floor=0.3)
SEEN = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
CHANNEL = "UC" + "c" * 22
OTHER = "UC" + "o" * 22
SEED = "seed0000000"


def vector(similarity: float) -> tuple[float, ...]:
    """A unit vector whose cosine similarity to `vector(1.0)` is `similarity`."""
    values = [0.0] * EMBEDDING_DIMENSIONS
    values[0] = similarity
    values[1] = math.sqrt(1 - similarity**2)
    return tuple(values)


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    with factory.begin() as session:
        for channel_id, title in [(CHANNEL, "Wood Shop"), (OTHER, "Other Shop")]:
            session.execute(
                text(
                    "INSERT INTO channels (id, title, thumbnail_url) "
                    "VALUES (:id, :title, 'https://example.invalid/' || :id)"
                ),
                {"id": channel_id, "title": title},
            )
        add(session, SEED, 1.0, title="Planing a board")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def add(
    session: Session,
    video_id: str,
    similarity: float | None = None,
    *,
    channel: str = CHANNEL,
    title: str | None = None,
    **columns: object,
) -> str:
    """Store a video, with an embedding at `similarity` to the seed's when given."""
    session.execute(
        text(
            """
            INSERT INTO videos (id, channel_id, title, description, duration_seconds,
                                published_at, thumbnail_url, view_count, live_status, is_short)
            VALUES (:id, :channel, :title, :description, :duration, '2026-10-01T00:00:00.000Z',
                    'https://example.invalid/' || :id, 1234, :live, :short)
            """
        ),
        {
            "id": video_id,
            "channel": channel,
            "title": title or f"Video {video_id}",
            "description": columns.get("description"),
            "duration": columns.get("duration", 600),
            "live": columns.get("live"),
            "short": columns.get("short", 0),
        },
    )
    if similarity is not None:
        store_embedding(session, video_id, vector(similarity))
    return video_id


def similar(sessions: sessionmaker[Session], limit: int = 8) -> list[SimilarVideo]:
    with sessions() as session:
        return similar_videos(session, SEED, limit, settings=SETTINGS)


def ids(videos: list[SimilarVideo]) -> list[str]:
    return [video.video_id for video in videos]


def test_nearest_neighbours_come_best_first_with_the_card_fields(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        add(session, "mid00000000", 0.6)
        add(session, "close000000", 0.9, title="Planing, again", channel=OTHER)
        add(session, "far00000000", 0.4)

    found = similar(sessions)

    assert ids(found) == ["close000000", "mid00000000", "far00000000"]
    assert [round(video.similarity or 0, 2) for video in found] == [0.9, 0.6, 0.4]
    closest = found[0]
    assert closest == SimilarVideo(
        video_id="close000000",
        title="Planing, again",
        duration_seconds=600,
        published_at="2026-10-01T00:00:00.000Z",
        thumbnail_url="https://example.invalid/close000000",
        view_count=1234,
        channel_id=OTHER,
        channel_title="Other Shop",
        channel_thumbnail_url=f"https://example.invalid/{OTHER}",
        watched=False,
        reason=SIMILAR_REASON,
        similarity=closest.similarity,
    )


def test_the_video_itself_is_not_listed(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add(session, "dup00000000", 1.0)  # a re-upload: as close as can be

    assert ids(similar(sessions)) == ["dup00000000"]


def test_neighbours_below_the_similarity_floor_are_left_out(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        add(session, "near0000000", 0.5)
        add(session, "unrelated00", 0.1)
        add(session, "opposite000", -0.8)

    assert ids(similar(sessions)) == ["near0000000"]


def test_the_list_is_capped(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        for n in range(40):
            add(session, f"video{n:06d}", 0.99 - n * 0.01)

    found = similar(sessions, limit=5)
    assert ids(found) == [f"video{n:06d}" for n in range(5)]
    assert len(similar(sessions)) == 8  # the default
    assert len(similar(sessions, limit=40)) == 40
    assert similar(sessions, limit=0) == []


def test_enough_neighbours_are_found_past_the_filtered_ones(
    sessions: sessionmaker[Session],
) -> None:
    """The nearest neighbours are all videos that can't be listed (watched here)."""
    with sessions.begin() as session:
        for n in range(70):
            add(session, f"seen{n:07d}", 0.99 - n * 0.001)
            record_watch_event(session, f"seen{n:07d}", "play", 0.0, 600.0)
        for n in range(3):
            add(session, f"fresh{n:06d}", 0.7 - n * 0.1)

    assert ids(similar(sessions)) == ["fresh000000", "fresh000001", "fresh000002"]


def test_watched_and_rated_videos_are_left_out(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add(session, "played00000", 0.9)
        add(session, "rated000000", 0.8)
        add(session, "opened00000", 0.7)  # opened, never played
        add(session, "unseen00000", 0.6)
        record_watch_event(session, "played00000", "play", 0.0, 600.0)
        record_watch_event(session, "opened00000", "close", 0.0, 600.0)
        set_rating(session, "rated000000", 2)

    assert ids(similar(sessions)) == ["opened00000", "unseen00000"]


def test_dismissed_videos_are_left_out(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add(session, "dismissed00", 0.9)
        add(session, "kept0000000", 0.8)
        session.execute(text("INSERT INTO feeds (id, date) VALUES (1, '2026-10-12')"))
        session.execute(
            text(
                """
                INSERT INTO feed_items (feed_id, video_id, position, source, score, breakdown,
                                        explanation, dismissed_at)
                VALUES (1, 'dismissed00', 0, 'subscription', 0, '{}', '', '2026-10-12T07:00:00Z')
                """
            )
        )

    assert ids(similar(sessions)) == ["kept0000000"]


def test_channels_that_are_muted_or_hidden_are_left_out(sessions: sessionmaker[Session]) -> None:
    channels = {
        name: "UC" + name[0] * 22 for name in ("muted", "blocked", "dismissed", "plain", "subbed")
    }
    with sessions.begin() as session:
        for name, channel_id in channels.items():
            session.execute(
                text("INSERT INTO channels (id, title) VALUES (:id, :id)"), {"id": channel_id}
            )
            add(session, f"{name:_<11}", 0.9, channel=channel_id)
        session.execute(
            text("INSERT INTO channel_prefs (channel_id, muted) VALUES (:id, 1)"),
            {"id": channels["muted"]},
        )
        session.execute(
            text("INSERT INTO channel_prefs (channel_id, muted) VALUES (:id, 0)"),
            {"id": channels["subbed"]},
        )
        hide(session, channels["blocked"], "blocked")
        hide(session, channels["dismissed"], "dismissed")  # only from Discover's suggestions

    assert sorted(ids(similar(sessions))) == ["plain______", "subbed_____"]


def test_what_the_feed_filters_out_is_left_out(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add(session, "short000000", 0.95, short=1)
        add(session, "tiny0000000", 0.94, duration=30)
        add(session, "live0000000", 0.93, live="is_live")
        add(session, "muted000000", 0.92, title="Planing, a clickbait special")
        add(session, "tagged00000", 0.91)
        add(session, "toolong0000", 0.9, duration=7200)
        add(session, "fine0000000", 0.8)
        add_keyword_mute(session, "clickbait")
        [hand_tools] = set_llm_tags(
            session, "tagged00000", [ProposedTag("hand tools", 0.9)], prompt_version=2
        )
        subscribe_tag(session, hand_tools, weight=-1.0)
        update_tag_subscription(session, hand_tools.id, hide=True)
        update_user_settings(session, {"feed_max_duration_seconds": 3600}, settings=SETTINGS)

    assert ids(similar(sessions)) == ["fine0000000"]


def test_youtubes_related_videos_are_listed_as_such(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add(session, "related0001", 0.7)
        add(session, "related0002", 0.9)
        add(session, "neighbour00", 0.8)
        record(session, ["related0001", "related0002"], source=RELATED, source_detail=SEED)

    found = similar(sessions)

    assert ids(found) == ["related0002", "neighbour00", "related0001"]
    assert [video.reason for video in found] == [RELATED_REASON, SIMILAR_REASON, RELATED_REASON]


def test_a_related_video_is_not_listed_twice(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add(session, "both0000000", 0.8)
        record(session, ["both0000000"], source=RELATED, source_detail=SEED)

    found = similar(sessions)

    assert ids(found) == ["both0000000"]
    assert found[0].reason == RELATED_REASON


def test_related_videos_without_a_similarity_come_last(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add(session, "older000000")
        add(session, "newer000000")
        add(session, "embedded000", 0.45)
        record(session, ["older000000"], source=RELATED, source_detail=SEED, now=SEEN)
        record(
            session,
            ["newer000000"],
            source=RELATED,
            source_detail=SEED,
            now=SEEN.replace(day=13),
        )
        record(session, ["embedded000"], source=RELATED, source_detail=SEED, now=SEEN)

    found = similar(sessions)

    assert ids(found) == ["embedded000", "newer000000", "older000000"]
    assert [video.similarity is None for video in found] == [False, True, True]


def test_without_an_embedding_only_related_videos_are_listed(
    tmp_path: Path,
) -> None:
    factory = open_database(tmp_path / "homefeed.sqlite")
    with factory.begin() as session:
        session.execute(text("INSERT INTO channels (id, title) VALUES (:id, 'C')"), {"id": CHANNEL})
        add(session, SEED)  # not embedded yet
        add(session, "related0001", 0.9)  # embedded, but there's nothing to compare it with
        add(session, "neighbour00", 0.9)
        record(session, ["related0001"], source=RELATED, source_detail=SEED)

    with factory() as session:
        found = similar_videos(session, SEED, settings=SETTINGS)
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()

    assert ids(found) == ["related0001"]
    assert found[0].similarity is None


def test_nothing_similar_yet(sessions: sessionmaker[Session]) -> None:
    assert similar(sessions) == []
    with sessions() as session:
        assert similar_videos(session, "unknown0000", settings=SETTINGS) == []


def test_related_videos_of_other_videos_are_not_listed(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add(session, "elsewhere00")
        record(session, ["elsewhere00"], source=RELATED, source_detail="other000000")
        record(session, ["elsewhere00"], source=SUBSCRIPTION, source_detail=CHANNEL)

    assert similar(sessions) == []
