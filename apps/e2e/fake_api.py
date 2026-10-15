"""The Homefeed API over a fake Gateway, for the Playwright flows.

Serves the real FastAPI app (`homefeed_api.main.app`) on 127.0.0.1:$E2E_API_PORT with:

- a `FakeGateway` holding two subscribed channels and their uploads, so nothing talks to
  YouTube, plus Metalworking, which Woodworking features and nobody subscribes to (Discover
  suggests it once Woodworking is liked) and Gardening, subscribed only with `noisy=true`;
- a feed refresh that polls subscriptions through the real pipeline, against a fake
  feed fetcher serving RSS built from the `FakeGateway`'s uploads;
- a stub embedding provider, and no network at all;
- a throwaway data dir ($E2E_DATA_DIR, or a new temp dir removed on exit);
- `POST /__e2e__/outside`, for the card specs: adds a video from a channel that isn't
  subscribed (found as related to a Woodworking video) and the LLM tagger's scores for it
  and for a subscribed video, then builds a new feed for today, and one more video from
  another channel that isn't subscribed, found after that, so it's Discovery's;
- `POST /__e2e__/pool`, for the wildcard specs: adds outside videos found as related to a
  Woodworking video three weeks ago, one channel each and untagged. That is too long ago
  for the feed (or Discovery) to have them, so they are what the wildcards draw from;
- `POST /__e2e__/duration`, which sets a video's length, to have a short one on hand;
- `POST /__e2e__/yesterday`, which moves every feed back a day, as if today's hadn't been
  built yet;
- `POST /__e2e__/reset`, which recreates the database, subscribes to both channels,
  stores their uploads as candidates (with LLM tags on some, see `VIDEO_TAGS`) and
  builds today's feed. Tests call it first. `?fresh=true` leaves it a fresh install
  instead: no subscriptions, no feed, first-run setup not done. `?noisy=true` also
  subscribes to Gardening, whose six uploads all end up in the feed: a channel that keeps
  showing up;
- `POST /__e2e__/similar`, which embeds videos at given similarities to a seed video and
  records what YouTube suggests next to it, for "Find more like this" (see `seed_similar`);
- `POST /__e2e__/channel-picture`, which gives a channel a picture, as looking it up does
  (the seeded channels have none);
- `POST /__e2e__/watch`, which records a play of a video as it was some days back, for the
  Insights recap that sets a week against the one before (a play through the API is always
  stamped now).

Run it with `uv run --package homefeed-api python fake_api.py`.
"""

import math
import os
import random
import shutil
import signal
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

    from homefeed_core.gateway.fake import FakeGateway
    from homefeed_core.gateway.rss import FeedFetcher


def configure(data_dir: Path) -> None:
    """Point the settings at `data_dir`, away from any `.env` of the checkout."""
    os.environ.update(
        DATA_DIR=str(data_dir),
        DATABASE_PATH=str(data_dir / "homefeed.sqlite"),
        FEED_SIZE="15",
        FEED_EXPLORATION_SLOTS="0",
        FEED_CANDIDATE_DAYS="7",
        LLM_PROVIDER="none",
    )
    # The settings use the nearest `.env` at or above the working directory.
    os.chdir(data_dir)


def main() -> None:
    owned = "E2E_DATA_DIR" not in os.environ
    data_dir = Path(os.environ.get("E2E_DATA_DIR") or tempfile.mkdtemp(prefix="homefeed-e2e-"))
    data_dir.mkdir(parents=True, exist_ok=True)
    port = int(os.environ.get("E2E_API_PORT", "8799"))
    configure(data_dir)

    import uvicorn

    app = build_app()
    reset_data()

    # uvicorn shuts down on SIGTERM, then re-raises it to the handler installed before
    # it ran: exit through `finally`, so the data dir is removed.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        if owned:
            shutil.rmtree(data_dir, ignore_errors=True)


# Seed data. Channel and video ids follow YouTube's formats (UC + 22, and 11 chars).

WOOD_ID = "UC" + "w" * 22
BIRDS_ID = "UC" + "b" * 22
METAL_ID = "UC" + "m" * 22
GARDEN_ID = "UC" + "g" * 22

# (video id, title, hours since upload); Birdwatching's uploads are the oldest, so a
# neutral prior ranks them last.
WOOD_VIDEOS = [
    ("wood0000001", "Sharpening a hand plane", 1),
    ("wood0000002", "Building a workbench", 2),
    ("wood0000003", "Cutting dovetails by hand", 3),
]
BIRDS_VIDEOS = [
    ("bird0000001", "Spotting warblers in spring", 30),
    ("bird0000002", "Owls at night", 31),
]
METAL_VIDEOS = [
    ("metal000001", "Welding aluminium at home", 5),
    ("metal000002", "Forging a knife blade", 6),
    ("metal000003", "Sharpening a chisel on a stone", 7),
]
GARDEN_VIDEOS = [(f"gard{n:07d}", f"Pruning roses, part {n}", 40 + n) for n in range(1, 7)]
# Tags as the LLM tagger would have stored them: (label, confidence) by video id.
VIDEO_TAGS = {
    "wood0000002": [("workbench", 0.9), ("woodworking", 0.8), ("hand tools", 0.5)],
    "wood0000003": [("woodworking", 0.7)],
    # Metalworking's uploads are stored, as a look at the channel would leave them, and
    # tagged, so its suggestion can say what it's about.
    "metal000001": [("metalworking", 0.9), ("welding", 0.8)],
    "metal000002": [("metalworking", 0.9), ("forging", 0.7), ("welding", 0.2)],
    "metal000003": [("metalworking", 0.8), ("sharpening", 0.6)],
}


def build_app() -> "FastAPI":
    from fastapi import Response, status
    from functools import partial

    from homefeed_api.main import app, get_embedder, get_feed_poll, get_gateway, get_playback
    from homefeed_core import pipeline
    from homefeed_core.embeddings import StubEmbeddingProvider

    app.dependency_overrides[get_gateway] = lambda: STATE["gateway"]
    app.dependency_overrides[get_playback] = lambda: STATE["playback"]
    # The real pipeline poll, fed by a fake feed fetcher instead of YouTube's RSS.
    app.dependency_overrides[get_feed_poll] = lambda: partial(
        pipeline.poll_subscriptions, fetch=make_feed_fetcher()
    )
    # A lambda: FastAPI would read the class's constructor parameters as request fields.
    app.dependency_overrides[get_embedder] = lambda: StubEmbeddingProvider()

    @app.post("/__e2e__/outside", include_in_schema=False)
    def e2e_outside() -> Response:
        seed_outside()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/__e2e__/pool", include_in_schema=False)
    def e2e_pool(count: int = 6) -> Response:
        seed_pool(count)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/__e2e__/duration", include_in_schema=False)
    def e2e_duration(body: dict[str, Any]) -> Response:
        set_duration(body["video_id"], int(body["seconds"]))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/__e2e__/yesterday", include_in_schema=False)
    def e2e_yesterday() -> Response:
        move_feeds_back_a_day()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/__e2e__/reset", include_in_schema=False)
    def e2e_reset(fresh: bool = False, noisy: bool = False) -> Response:
        reset_data(fresh=fresh, noisy=noisy)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/__e2e__/similar", include_in_schema=False)
    def e2e_similar(body: dict[str, Any]) -> Response:
        seed_similar(body["seed"], body["similarities"], body.get("related", []))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/__e2e__/channel-picture", include_in_schema=False)
    def e2e_channel_picture(body: dict[str, Any]) -> Response:
        set_channel_picture(body["channel_id"], body["url"])
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/__e2e__/watch", include_in_schema=False)
    def e2e_watch(body: dict[str, Any]) -> Response:
        record_play(body["video_id"], days_ago=body.get("days_ago", 0))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


# Videos of channels that aren't subscribed: (video id, title). The first is in the feed
# `seed_outside` builds, the second is for the Discovery carousel.
OUTSIDE_ID = "UC" + "o" * 22
OUTSIDE_VIDEO = ("outs0000001", "Turning a bowl from a green log")
DISCOVERY_ID = "UC" + "j" * 22
DISCOVERY_VIDEO = ("disc0000001", "Cutting mortises by hand")

STATE: dict[str, object] = {}


def seed_outside() -> None:
    """Add what the card specs need on top of `reset_data`: a video of an unsubscribed
    channel, found as related to a Woodworking video, the LLM tagger's scores for it
    (clickbait) and for a subscribed video (in-depth), a new feed for today, and a video
    of another unsubscribed channel that turns up after the feed was built."""
    from homefeed_core import feeds, videos
    from homefeed_core.candidates import CHANNEL_GRAPH, RELATED, record
    from homefeed_core.db import get_session_factory
    from homefeed_core.gateway.fake import make_channel, make_video
    from homefeed_core.llm_tags import LLMTags, store_tags

    now = datetime.now(UTC)
    outside = make_video(
        OUTSIDE_VIDEO[0],
        channel=make_channel(OUTSIDE_ID, title="Lathe Works", handle="@lathe"),
        title=OUTSIDE_VIDEO[1],
        published_at=now - timedelta(minutes=90),
        duration_seconds=4140,
        view_count=48_000,
    )
    discovery = make_video(
        DISCOVERY_VIDEO[0],
        channel=make_channel(DISCOVERY_ID, title="Joinery Journal", handle="@joinery"),
        title=DISCOVERY_VIDEO[1],
        published_at=now - timedelta(hours=5),
        duration_seconds=1500,
        view_count=9_000,
    )
    with get_session_factory().begin() as session:
        videos.store_video(session, outside)
        record(session, [outside.id], source=RELATED, source_detail=WOOD_VIDEOS[0][0])
        store_tags(session, outside.id, LLMTags("hobbies", 0.2, 0.9, 0.1), model="e2e")
        store_tags(session, WOOD_VIDEOS[1][0], LLMTags("hobbies", 0.8, 0.1, 0.0), model="e2e")
        feeds.build_feed(session, rng=random.Random(0))
        videos.store_video(session, discovery)
        record(session, [discovery.id], source=CHANNEL_GRAPH, source_detail=WOOD_ID)


def seed_pool(count: int) -> None:
    """Add `count` videos of channels that aren't subscribed (`Pool 1`, `Pool 2`, ...), found
    as related to a Woodworking video three weeks ago and untagged. The feed only looks a
    week back, so it never has them, not even once "Show more" has nothing more; the
    wildcards look further."""
    from homefeed_core import videos
    from homefeed_core.candidates import RELATED, record
    from homefeed_core.db import get_session_factory
    from homefeed_core.gateway.fake import make_channel, make_video

    found = datetime.now(UTC) - timedelta(days=21)
    with get_session_factory().begin() as session:
        for n in range(1, count + 1):
            video = make_video(
                f"pool{n:07d}",
                channel=make_channel(
                    f"UCpool{n:018d}", title=f"Pool channel {n}", handle=f"@pool{n}"
                ),
                title=f"Pool video {n}",
                published_at=found - timedelta(hours=n),
                duration_seconds=900 + 30 * n,
                view_count=100 * n,
            )
            videos.store_video(session, video)
            record(
                session,
                [video.id],
                source=RELATED,
                source_detail=WOOD_VIDEOS[0][0],
                now=found,
            )


def set_duration(video_id: str, seconds: int) -> None:
    """Give a video a length, as enriching it would."""
    from sqlalchemy import text

    from homefeed_core.db import get_session_factory

    with get_session_factory().begin() as session:
        session.execute(
            text("UPDATE videos SET duration_seconds = :seconds WHERE id = :id"),
            {"id": video_id, "seconds": seconds},
        )


def move_feeds_back_a_day() -> None:
    """Date every feed a day earlier, so there is none for today."""
    from sqlalchemy import text

    from homefeed_core.db import get_session_factory

    with get_session_factory().begin() as session:
        session.execute(text("UPDATE feeds SET date = date(date, '-1 day')"))


def make_gateway() -> "FakeGateway":
    from homefeed_core.gateway.fake import FakeGateway, make_channel, make_video

    now = datetime.now(UTC)
    gateway = FakeGateway()
    for channel_id, title, handle, uploads in [
        (WOOD_ID, "Woodworking", "@wood", WOOD_VIDEOS),
        (BIRDS_ID, "Birdwatching", "@birds", BIRDS_VIDEOS),
        (METAL_ID, "Metalworking", "@metal", METAL_VIDEOS),
        (GARDEN_ID, "Gardening", "@garden", GARDEN_VIDEOS),
    ]:
        channel = make_channel(channel_id, title=title, handle=handle)
        gateway.add_channel(
            channel,
            [
                make_video(
                    video_id,
                    channel=channel,
                    title=video_title,
                    description=f"{video_title}, a video on {title}.",
                    published_at=now - timedelta(hours=hours),
                    duration_seconds=600 + 60 * n,
                    view_count=1000 * (n + 1),
                )
                for n, (video_id, video_title, hours) in enumerate(uploads)
            ],
        )
        # Searching for the channel's lowercase name finds it by its newest video.
        gateway.add_search(title.lower(), [gateway.videos[gateway.uploads[channel_id][0].id]])
    # Woodworking features Metalworking, which nobody subscribes to.
    gateway.add_featured(WOOD_ID, [gateway.channels[METAL_ID]], subscriber_count=48_000)
    return gateway


def make_feed_fetcher() -> "FeedFetcher":
    """A `FeedFetcher` that serves each channel's uploads as the channel RSS feed the
    poller parses, so a feed refresh polls subscriptions like the real thing would."""
    from xml.sax.saxutils import escape

    from homefeed_core.gateway.fake import FakeGateway

    gateway = STATE["gateway"]
    assert isinstance(gateway, FakeGateway)

    def fetch(channel_id: str) -> bytes:
        uploads = [gateway.videos[upload.id] for upload in gateway.uploads[channel_id]]
        # YouTube lists newest first, as `parse_feed` documents. The poller looks
        # namespaces up by prefix (atom, yt, media), so bind each explicitly.
        entries = "".join(
            f"""
              <atom:entry>
                <yt:videoId>{video.id}</yt:videoId>
                <yt:channelId>{channel_id}</yt:channelId>
                <atom:title>{escape(video.title)}</atom:title>
                <atom:link rel="alternate" href="https://www.youtube.com/watch?v={video.id}"/>
                <atom:published>{video.published_at.isoformat()}</atom:published>
                <atom:updated>{video.published_at.isoformat()}</atom:updated>
                <media:group>
                  <media:title>{escape(video.title)}</media:title>
                  <media:description>{escape(video.description or "")}</media:description>
                  <media:community>
                    <media:statistics views="{video.view_count or 0}"/>
                  </media:community>
                </media:group>
              </atom:entry>"""
            for video in reversed(uploads)
        )
        return f"""<?xml version="1.0" encoding="UTF-8"?>
            <atom:feed xmlns:atom="http://www.w3.org/2005/Atom"
                       xmlns:yt="http://www.youtube.com/xml/schemas/2015"
                       xmlns:media="http://search.yahoo.com/mrss/">
              <yt:channelId>{channel_id}</yt:channelId>
              <atom:title>{escape(gateway.channels[channel_id].title)}</atom:title>{entries}
            </atom:feed>""".encode()

    return fetch


def seed_similar(seed: str, similarities: dict[str, float], related: list[str]) -> None:
    """Embed `seed`, and every video in `similarities` so its cosine similarity to the seed
    is the given one (a video not listed has no embedding), and record `related` as what
    YouTube suggests next to `seed`."""
    from homefeed_core.candidates import RELATED, record
    from homefeed_core.db import get_session_factory
    from homefeed_core.embeddings import EMBEDDING_DIMENSIONS, store_embedding

    def vector(similarity: float) -> list[float]:
        values = [0.0] * EMBEDDING_DIMENSIONS
        values[0] = similarity
        values[1] = math.sqrt(1 - similarity**2)
        return values

    with get_session_factory().begin() as session:
        store_embedding(session, seed, vector(1.0))
        for video_id, similarity in similarities.items():
            store_embedding(session, video_id, vector(similarity))
        record(session, related, source=RELATED, source_detail=seed)


def set_channel_picture(channel_id: str, url: str) -> None:
    """Give a channel a picture, as looking the channel up (subscribing, its page) stores it."""
    from sqlalchemy import text

    from homefeed_core.db import get_session_factory

    with get_session_factory().begin() as session:
        session.execute(
            text("UPDATE channels SET thumbnail_url = :url WHERE id = :id"),
            {"id": channel_id, "url": url},
        )


def record_play(video_id: str, *, days_ago: float = 0) -> None:
    """Record a play of a video as it was `days_ago` days back, as watching it then would
    have left it."""
    from homefeed_core import watch_events
    from homefeed_core.db import get_session_factory
    from homefeed_core.gateway.events import format_timestamp

    at = datetime.now(UTC) - timedelta(days=days_ago)
    with get_session_factory().begin() as session:
        watch_events.record_watch_event(
            session, video_id, "play", 0.0, 600.0, at=format_timestamp(at)
        )


def reset_data(*, fresh: bool = False, noisy: bool = False) -> None:
    """Recreate the database and seed it: two subscriptions (three when `noisy`), their
    uploads, a feed. A fresh install gets none of that."""
    from homefeed_core import curation, feeds, playback, tags, videos
    from homefeed_core.candidates import SUBSCRIPTION, record
    from homefeed_core.config import get_settings
    from homefeed_core.db import get_session_factory
    from homefeed_core.gateway.urls import channel_url
    from homefeed_core.llm_tags import TAG_PROMPT_VERSION

    get_settings.cache_clear()
    if get_session_factory.cache_info().currsize:
        get_session_factory().kw["bind"].dispose()
        get_session_factory.cache_clear()
    database = get_settings().database_path
    for suffix in ("", "-wal", "-shm"):
        Path(f"{database}{suffix}").unlink(missing_ok=True)

    gateway = make_gateway()
    STATE["gateway"] = gateway
    STATE["playback"] = playback.Playback(gateway)

    if fresh:
        with get_session_factory().begin():  # creates the database
            pass
        return
    subscribed = [WOOD_ID, BIRDS_ID, *([GARDEN_ID] if noisy else [])]
    with get_session_factory().begin() as session:
        for channel in (gateway.channels[channel_id] for channel_id in subscribed):
            curation.subscribe(session, gateway, channel_url(channel.id))
            uploads = [gateway.videos[upload.id] for upload in gateway.uploads[channel.id]]
            for video in uploads:
                videos.store_video(session, video)
            record(
                session,
                [video.id for video in uploads],
                source=SUBSCRIPTION,
                source_detail=channel.id,
            )
        for upload in gateway.uploads[METAL_ID]:
            videos.store_video(session, gateway.videos[upload.id])
        for video_id, proposals in VIDEO_TAGS.items():
            tags.set_llm_tags(
                session,
                video_id,
                [tags.ProposedTag(label, confidence) for label, confidence in proposals],
                prompt_version=TAG_PROMPT_VERSION,
            )
        feed = feeds.build_feed(session, rng=random.Random(0))
        # A feed shows two videos of a channel at most. "Show more" twice brings in
        # the rest, so Gardening has six picks.
        for _ in range(2 if noisy else 0):
            feeds.extend_feed(session, feed.id, rng=random.Random(0))
    gateway.calls.clear()


if __name__ == "__main__":
    sys.exit(main())
