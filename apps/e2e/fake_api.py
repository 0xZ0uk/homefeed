"""The Homefeed API over a fake Gateway, for the Playwright flows.

Serves the real FastAPI app (`homefeed_api.main.app`) on 127.0.0.1:$E2E_API_PORT with:

- a `FakeGateway` holding two channels and their uploads, so nothing talks to YouTube;
- no RSS polling on feed refresh, and a stub embedding provider;
- a throwaway data dir ($E2E_DATA_DIR, or a new temp dir removed on exit);
- `POST /__e2e__/reset`, which recreates the database, subscribes to both channels,
  stores their uploads as candidates (with LLM tags on some, see `VIDEO_TAGS`) and
  builds today's feed. Tests call it first. `?fresh=true` leaves it a fresh install
  instead: no subscriptions, no feed, first-run setup not done;
- a feed refresh that "polls" by storing the subscribed channels' uploads as candidates
  (the real poller would fetch RSS), so subscribing then building a feed works.

Run it with `uv run --package homefeed-api python fake_api.py`.
"""

import os
import random
import shutil
import signal
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from homefeed_core.gateway.fake import FakeGateway


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
# Tags as the LLM tagger would have stored them: (label, confidence) by video id.
VIDEO_TAGS = {
    "wood0000002": [("workbench", 0.9), ("woodworking", 0.8), ("hand tools", 0.5)],
    "wood0000003": [("woodworking", 0.7)],
}


def build_app() -> "FastAPI":
    from fastapi import Response, status

    from homefeed_api.main import app, get_embedder, get_feed_poll, get_gateway, get_playback
    from homefeed_core.embeddings import StubEmbeddingProvider

    app.dependency_overrides[get_gateway] = lambda: STATE["gateway"]
    app.dependency_overrides[get_playback] = lambda: STATE["playback"]
    app.dependency_overrides[get_feed_poll] = lambda: poll_subscriptions
    # A lambda: FastAPI would read the class's constructor parameters as request fields.
    app.dependency_overrides[get_embedder] = lambda: StubEmbeddingProvider()

    @app.post("/__e2e__/reset", include_in_schema=False)
    def e2e_reset(fresh: bool = False) -> Response:
        reset_data(fresh=fresh)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


STATE: dict[str, object] = {}


def make_gateway() -> "FakeGateway":
    from homefeed_core.gateway.fake import FakeGateway, make_channel, make_video

    now = datetime.now(UTC)
    gateway = FakeGateway()
    for channel_id, title, handle, uploads in [
        (WOOD_ID, "Woodworking", "@wood", WOOD_VIDEOS),
        (BIRDS_ID, "Birdwatching", "@birds", BIRDS_VIDEOS),
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
    return gateway


def poll_subscriptions() -> None:
    """Stand in for the RSS poller: store the subscribed channels' uploads as candidates."""
    from homefeed_core import curation, videos
    from homefeed_core.candidates import SUBSCRIPTION, record
    from homefeed_core.db import get_session_factory
    from homefeed_core.gateway.fake import FakeGateway

    gateway = STATE["gateway"]
    assert isinstance(gateway, FakeGateway)
    with get_session_factory().begin() as session:
        for channel_id in curation.subscribed_channel_ids(session):
            uploads = [gateway.videos[upload.id] for upload in gateway.uploads[channel_id]]
            for video in uploads:
                videos.store_video(session, video)
            record(
                session,
                [video.id for video in uploads],
                source=SUBSCRIPTION,
                source_detail=channel_id,
            )


def reset_data(*, fresh: bool = False) -> None:
    """Recreate the database and seed it: two subscriptions, their uploads, a feed.
    A fresh install gets none of that."""
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
    with get_session_factory().begin() as session:
        for channel in gateway.channels.values():
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
        for video_id, proposals in VIDEO_TAGS.items():
            tags.set_llm_tags(
                session,
                video_id,
                [tags.ProposedTag(label, confidence) for label, confidence in proposals],
                prompt_version=TAG_PROMPT_VERSION,
            )
        feeds.build_feed(session, rng=random.Random(0))
    gateway.calls.clear()


if __name__ == "__main__":
    sys.exit(main())
