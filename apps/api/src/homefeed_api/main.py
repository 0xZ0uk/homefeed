import datetime as dt
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Response, status
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from homefeed_core import curation, feeds, playback, poller, ratings, videos, watch_events
from homefeed_core.db import get_session_factory
from homefeed_core.gateway import (
    Gateway,
    GatewayError,
    UnavailableError,
    UnsupportedUrlError,
    create_gateway,
)
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.grades import Grade


def operation_id(route: APIRoute) -> str:
    """Use the handler name as the OpenAPI operation id, so the generated client reads well."""
    return route.name


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    get_session_factory()  # create and migrate the database before serving
    yield


app = FastAPI(title="Homefeed API", generate_unique_id_function=operation_id, lifespan=lifespan)


def get_session() -> Iterator[Session]:
    """A session whose transaction commits when the handler returns, or rolls back on error."""
    with get_session_factory().begin() as session:
        yield session


@lru_cache
def get_gateway() -> Gateway:
    """The process-wide Gateway (shared so its rate limiting applies across requests).

    Tests override this dependency with a `FakeGateway`.
    """
    return create_gateway()


@lru_cache
def get_playback() -> playback.Playback:
    """The process-wide playback service (its caches hold stream URLs and metadata).

    Tests override this dependency with one over a `FakeGateway`.
    """
    return playback.Playback(get_gateway())


def get_feed_poll() -> Callable[[], object] | None:
    """What `POST /feed/refresh` runs to poll subscriptions before building the feed.

    Tests override this dependency so a refresh doesn't fetch RSS feeds.
    """
    return poller.poll_due_channels


SessionDep = Annotated[Session, Depends(get_session)]
GatewayDep = Annotated[Gateway, Depends(get_gateway)]
PlaybackDep = Annotated[playback.Playback, Depends(get_playback)]
FeedPollDep = Annotated[Callable[[], object] | None, Depends(get_feed_poll)]
VideoId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{11}$", description="YouTube video id")]
FormatId = Annotated[
    str,
    Path(
        pattern=r"^[A-Za-z0-9_-]{1,40}$",
        description='Stream (format) id from the manifest, e.g. "137", "140-drc" or "251-1"',
    ),
]
ChannelId = Annotated[
    str, Path(pattern=r"^UC[A-Za-z0-9_-]{22}$", description="YouTube channel id (UC...)")
]


class ErrorDetail(BaseModel):
    detail: str


class Health(BaseModel):
    status: Literal["ok"]


@app.get("/health")
def health() -> Health:
    return Health(status="ok")


class RatingInput(BaseModel):
    grade: Grade


@app.put("/ratings/{video_id}", tags=["ratings"])
def rate_video(video_id: VideoId, body: RatingInput, session: SessionDep) -> ratings.Rating:
    """Create or update the rating for a video."""
    return ratings.set_rating(session, video_id, body.grade)


@app.delete(
    "/ratings/{video_id}",
    tags=["ratings"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "The video has no rating"}},
)
def delete_rating(video_id: VideoId, session: SessionDep) -> Response:
    """Remove the rating for a video."""
    if not ratings.delete_rating(session, video_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rating not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get(
    "/ratings/{video_id}",
    tags=["ratings"],
    responses={404: {"model": ErrorDetail, "description": "The video has no rating"}},
)
def get_rating(video_id: VideoId, session: SessionDep) -> ratings.Rating:
    """The rating for a video."""
    rating = ratings.get_rating(session, video_id)
    if rating is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rating not found")
    return rating


class WatchEventInput(BaseModel):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$", description="YouTube video id")
    event_type: watch_events.WatchEventType
    position: float = Field(ge=0, le=1e7, description="Playback position in seconds")
    duration: float | None = Field(
        default=None, gt=0, le=1e7, description="Video duration in seconds, if known"
    )


@app.post("/watch-events", tags=["watching"], status_code=status.HTTP_201_CREATED)
def record_watch_event(body: WatchEventInput, session: SessionDep) -> watch_events.WatchEvent:
    """Record a player event (play, pause, seeked, ended or close) with its position.

    A `play` marks the video as watched, so it leaves future feeds.
    """
    return watch_events.record_watch_event(
        session, body.video_id, body.event_type, body.position, body.duration
    )


class SubscribeInput(BaseModel):
    url: str = Field(
        min_length=1,
        max_length=2000,
        description="A channel URL in any form (/@handle, /channel/UC..., /c/..., /user/...) "
        "or a bare @handle",
    )


class ChannelPrefsInput(BaseModel):
    """Preferences to change; omitted fields keep their current value."""

    prior: curation.Prior | None = None
    pinned: bool | None = None
    muted: bool | None = None


CHANNEL_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorDetail, "description": "The channel is not subscribed"}
}


@app.get("/channels", tags=["channels"])
def list_channels(session: SessionDep) -> list[curation.SubscribedChannel]:
    """All subscribed channels with their preferences, pinned first, then by title."""
    return curation.list_channels(session)


@app.post(
    "/channels",
    tags=["channels"],
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": curation.SubscribedChannel, "description": "Already subscribed"},
        404: {"model": ErrorDetail, "description": "The channel doesn't exist"},
        502: {"model": ErrorDetail, "description": "YouTube could not be reached"},
    },
)
def subscribe_channel(
    body: SubscribeInput, session: SessionDep, gateway: GatewayDep, response: Response
) -> curation.SubscribedChannel:
    """Subscribe to a channel by URL.

    Subscribing again returns 200 and keeps the channel's preferences. A URL that isn't a
    YouTube channel link (or a video/playlist link) is a 422 with a string `detail`.
    """
    try:
        channel, created = curation.subscribe(session, gateway, body.url)
    except (curation.NotAChannelUrlError, UnsupportedUrlError) as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except UnavailableError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except GatewayError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    if not created:
        response.status_code = status.HTTP_200_OK
    return channel


@app.patch("/channels/{channel_id}", tags=["channels"], responses=CHANNEL_NOT_FOUND)
def update_channel(
    channel_id: ChannelId, body: ChannelPrefsInput, session: SessionDep
) -> curation.SubscribedChannel:
    """Change a subscribed channel's prior, pin or mute."""
    channel = curation.update_channel(
        session, channel_id, prior=body.prior, pinned=body.pinned, muted=body.muted
    )
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not subscribed")
    return channel


@app.delete(
    "/channels/{channel_id}",
    tags=["channels"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CHANNEL_NOT_FOUND,
)
def unsubscribe_channel(channel_id: ChannelId, session: SessionDep) -> Response:
    """Unsubscribe from a channel, dropping its preferences."""
    if not curation.unsubscribe(session, channel_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not subscribed")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ScoreBreakdownOut(BaseModel):
    """How an item's score was made: `alpha * model + channel + sum(topics) = final`."""

    model: float
    alpha: float
    channel: float
    topics: dict[str, float]
    final: float


class FeedItemOut(BaseModel):
    id: int
    position: int = Field(description="0-based position in the feed")
    video_id: str
    title: str
    description: str | None
    duration_seconds: int | None = Field(description="Unknown for videos only seen in RSS")
    published_at: str | None = Field(description="Upload time, ISO 8601 UTC")
    thumbnail_url: str | None
    view_count: int | None
    channel_id: str
    channel_title: str
    channel_handle: str | None
    channel_thumbnail_url: str | None
    source: str
    source_detail: str | None
    score: float
    breakdown: ScoreBreakdownOut
    explanation: str
    is_pinned: bool
    is_exploration: bool
    selection_probability: float | None
    dismissed_at: str | None
    dismiss_reason: str | None


class FeedOut(BaseModel):
    id: int
    date: dt.date = Field(description="Local calendar date the feed is for")
    created_at: str = Field(description="ISO 8601 UTC")
    model_version: str | None = Field(description="None while ranking is rules-only")
    items: list[FeedItemOut]


class FeedSummaryOut(BaseModel):
    id: int
    date: dt.date
    created_at: str
    model_version: str | None
    item_count: int


def _feed_out(feed: feeds.Feed) -> FeedOut:
    return FeedOut(
        id=feed.id,
        date=feed.date,
        created_at=feed.created_at,
        model_version=feed.model_version,
        items=[
            FeedItemOut.model_validate(
                {
                    **vars(item),
                    "breakdown": ScoreBreakdownOut(
                        model=item.breakdown.model,
                        alpha=item.breakdown.alpha,
                        channel=item.breakdown.channel,
                        topics=dict(item.breakdown.topics),
                        final=item.breakdown.final,
                    ),
                }
            )
            for item in feed.items
        ],
    )


FEED_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorDetail, "description": "No feed has been built for the date"}
}


def _feed_or_404(session: Session, feed_date: dt.date) -> FeedOut:
    feed = feeds.get_feed(session, feed_date)
    if feed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No feed for {feed_date.isoformat()}")
    return _feed_out(feed)


@app.get("/feed/today", tags=["feed"], responses=FEED_NOT_FOUND)
def get_today_feed(session: SessionDep) -> FeedOut:
    """Today's feed (local date): the latest one built today."""
    return _feed_or_404(session, feeds.local_today())


@app.get("/feed/{feed_date}", tags=["feed"], responses=FEED_NOT_FOUND)
def get_feed(
    feed_date: Annotated[dt.date, Path(description="Local date, YYYY-MM-DD")], session: SessionDep
) -> FeedOut:
    """The latest feed built for a date."""
    return _feed_or_404(session, feed_date)


@app.get("/feeds", tags=["feed"])
def list_feeds(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=365)] = 30
) -> list[FeedSummaryOut]:
    """Feed history: the latest feed of each date, newest first."""
    return [
        FeedSummaryOut.model_validate(vars(summary))
        for summary in feeds.list_feeds(session, limit=limit)
    ]


@app.post("/feed/refresh", tags=["feed"])
def refresh_feed(poll: FeedPollDep) -> FeedOut:
    """Poll due subscriptions, then build and store a new feed for today.

    A failed poll doesn't fail the refresh; the feed is built from stored candidates.
    """
    return _feed_out(feeds.refresh_feed(poll=poll))


class ChapterOut(BaseModel):
    title: str
    start_seconds: float
    end_seconds: float


class VideoOut(BaseModel):
    id: str
    title: str
    description: str | None
    channel_id: str
    channel_title: str
    channel_handle: str | None
    duration_seconds: int | None
    published_at: str | None = Field(description="Upload time, ISO 8601 UTC")
    thumbnail_url: str | None
    live_status: str | None
    chapters: list[ChapterOut]
    is_stale: bool = Field(
        description="True when YouTube couldn't be reached and this is the stored copy"
    )


VIDEO_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorDetail, "description": "The video doesn't exist or can't be watched"},
    502: {"model": ErrorDetail, "description": "YouTube could not be reached"},
}


def _gateway_http_error(error: GatewayError) -> HTTPException:
    if isinstance(error, UnavailableError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(error))
    return HTTPException(status.HTTP_502_BAD_GATEWAY, str(error))


@app.get("/videos/{video_id}", tags=["videos"], responses=VIDEO_ERRORS)
def get_video(video_id: VideoId, session: SessionDep, player: PlaybackDep) -> VideoOut:
    """A video's metadata (title, channel, description, ...), stored in `videos`.

    When YouTube can't be reached, the stored copy is returned with `is_stale`.
    """
    try:
        video = player.video(video_id)
    except UnavailableError as error:
        raise _gateway_http_error(error) from error
    except GatewayError as error:
        stored = videos.get_stored_video(session, video_id)
        if stored is None:
            raise _gateway_http_error(error) from error
        return VideoOut.model_validate({**vars(stored), "chapters": [], "is_stale": True})
    videos.store_video(session, video)
    return VideoOut(
        id=video.id,
        title=video.title,
        description=video.description,
        channel_id=video.channel_id,
        channel_title=video.channel_title,
        channel_handle=video.channel_handle,
        duration_seconds=video.duration_seconds,
        published_at=(
            format_timestamp(video.published_at) if video.published_at is not None else None
        ),
        thumbnail_url=video.thumbnail_url,
        live_status=video.live_status,
        chapters=[ChapterOut.model_validate(vars(chapter)) for chapter in video.chapters],
        is_stale=False,
    )


@app.get(
    "/videos/{video_id}/manifest.mpd",
    tags=["videos"],
    response_class=Response,
    responses={
        200: {"content": {playback.MPD_CONTENT_TYPE: {}}, "description": "A DASH MPD"},
        **VIDEO_ERRORS,
        422: {"model": ErrorDetail, "description": "The video has no playable streams"},
    },
)
def get_manifest(video_id: VideoId, player: PlaybackDep) -> Response:
    """A DASH manifest of the video's streams. Its media URLs are relative
    (`media/{itag}`), so they resolve against wherever the manifest was fetched from."""
    try:
        mpd = player.manifest(video_id)
    except GatewayError as error:
        raise _gateway_http_error(error) from error
    except playback.NoPlayableStreamsError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    return Response(
        mpd, media_type=playback.MPD_CONTENT_TYPE, headers={"Cache-Control": "private, no-cache"}
    )


@app.get(
    "/videos/{video_id}/media/{itag}",
    tags=["videos"],
    response_class=StreamingResponse,
    responses={
        200: {"content": {"video/mp4": {}, "audio/mp4": {}, "video/webm": {}, "audio/webm": {}}},
        206: {"description": "The requested byte range"},
        404: {"model": ErrorDetail, "description": "No such video or stream"},
        409: {"model": ErrorDetail, "description": "The stream changed; reload the manifest"},
        416: {"description": "The range is outside the stream"},
        502: {"model": ErrorDetail, "description": "YouTube could not be reached"},
    },
)
def get_media(
    video_id: VideoId,
    itag: FormatId,
    player: PlaybackDep,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    """Proxy one stream's bytes, honouring a single `Range: bytes=...` (206).

    Stream URLs are resolved (and re-resolved when they expire) through the Gateway.
    """
    try:
        media = player.proxy_range(video_id, itag, range_header)
    except playback.RangeNotSatisfiable as error:
        headers = {"Content-Range": f"bytes */{error.total}"} if error.total else {}
        return Response(status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE, headers=headers)
    except playback.StreamNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except playback.StreamChangedError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except GatewayError as error:
        raise _gateway_http_error(error) from error
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(media.content_length),
        "Cache-Control": "private, max-age=86400",
    }
    if media.content_range is not None:
        headers["Content-Range"] = media.content_range
    return StreamingResponse(
        media.body, status_code=media.status, media_type=media.content_type, headers=headers
    )
