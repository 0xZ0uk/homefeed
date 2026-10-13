import datetime as dt
import json
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated, Any, Literal

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Path,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from homefeed_core import (
    channel_graph,
    curation,
    exporter,
    external_sources,
    extractor_status,
    feeds,
    history,
    importer,
    insights,
    playback,
    playlists,
    poller,
    queue,
    ranking_models,
    ratings,
    saved_searches,
    scores,
    sponsorblock,
    videos,
    watch_events,
)
from homefeed_core.db import get_session_factory
from homefeed_core.embeddings import EmbeddingProvider, get_embedding_provider
from homefeed_core.gateway import (
    DEFAULT_COMMENTS_LIMIT,
    DEFAULT_SEARCH_LIMIT,
    MAX_COMMENTS_LIMIT,
    MAX_SEARCH_LIMIT,
    SEARCH_QUERY_MAX_LENGTH,
    Gateway,
    GatewayError,
    SearchDuration,
    SearchFilters,
    SearchResult,
    SearchSort,
    SearchUploadDate,
    UnavailableError,
    UnsupportedUrlError,
    create_gateway,
)
from homefeed_core.gateway.events import format_timestamp


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
    return playback.Playback(get_gateway(), sponsorblock=sponsorblock.create_sponsorblock())


def get_embedder() -> EmbeddingProvider:
    """The process-wide embedding provider, for topic descriptions.

    The model loads on first use, so the API only loads it once a topic is saved. Tests
    override this dependency with a `StubEmbeddingProvider`.
    """
    return get_embedding_provider()


def get_feed_poll() -> Callable[[], object] | None:
    """What `POST /feed/refresh` runs to poll subscriptions before building the feed.

    Tests override this dependency so a refresh doesn't fetch RSS feeds.
    """
    return poller.poll_due_channels


SessionDep = Annotated[Session, Depends(get_session)]
GatewayDep = Annotated[Gateway, Depends(get_gateway)]
PlaybackDep = Annotated[playback.Playback, Depends(get_playback)]
EmbedderDep = Annotated[EmbeddingProvider, Depends(get_embedder)]
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


ExtractorHealth = Literal["ok", "degraded", "failing", "unknown"]


class OperationStatusOut(BaseModel):
    operation: str = Field(description='Gateway operation, e.g. "get_video" or "search"')
    health: ExtractorHealth = Field(
        description="failing: its latest events all failed in a way that points at the "
        "extractor; degraded: some such failures; ok: none (a removed video or an "
        "unsupported URL doesn't count)"
    )
    total: int
    successes: int
    failures: int = Field(description="All failures, including ones about the target")
    breakage_failures: int = Field(description="Failures that point at the extractor")
    success_rate: float | None = Field(description="successes / total")
    avg_duration_ms: int | None
    last_at: dt.datetime
    last_success_at: dt.datetime | None
    last_failure_at: dt.datetime | None
    last_error_kind: str | None = Field(description="Kind of the latest failure in the window")
    last_error: str | None


class FailedEventOut(BaseModel):
    id: int
    operation: str
    target: str | None = Field(description="The video id, channel id, URL or query asked for")
    error_kind: str | None
    error: str | None
    attempts: int
    at: dt.datetime
    breakage: bool = Field(
        description="Whether the failure points at the extractor rather than the target"
    )


class SmokeTestRunOut(BaseModel):
    at: dt.datetime
    success: bool
    error: str | None = Field(description="Which checks failed and why")
    duration_ms: int | None


class ExtractorStatusOut(BaseModel):
    since: dt.datetime = Field(description="Start of the window")
    hours: int
    health: ExtractorHealth = Field(description="The worst of the operations' health")
    operations: list[OperationStatusOut] = Field(description="Operations with events, by name")
    recent_failures: list[FailedEventOut] = Field(description="Newest first")
    last_smoke_test: SmokeTestRunOut | None = Field(
        description="The latest live smoke test run, whenever it was; null if it never ran "
        "(it is opt-in: GATEWAY_SMOKE_TEST_TIME)"
    )


@app.get("/status/extractors", tags=["status"])
def get_extractor_status(
    session: SessionDep,
    hours: Annotated[
        int,
        Query(ge=1, le=extractor_status.MAX_HOURS, description="Window, in hours up to now"),
    ] = extractor_status.DEFAULT_HOURS,
) -> ExtractorStatusOut:
    """Extraction health: the Gateway's recorded outcomes (`extractor_events`) of the
    last `hours`, aggregated per operation, the latest failures and the latest live
    smoke test run."""
    return ExtractorStatusOut.model_validate(
        extractor_status.extractor_status(session, hours=hours), from_attributes=True
    )


class RatingInput(BaseModel):
    score: float = Field(
        ge=scores.MIN_SCORE,
        le=scores.MAX_SCORE,
        description="1.0 to 10.0, with at most one decimal, e.g. 7.5",
    )

    @field_validator("score")
    @classmethod
    def _one_decimal(cls, score: float) -> float:
        return scores.check_score(score)


@app.put("/ratings/{video_id}", tags=["ratings"])
def rate_video(video_id: VideoId, body: RatingInput, session: SessionDep) -> ratings.Rating:
    """Create or update the rating for a video."""
    return ratings.set_rating(session, video_id, body.score)


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

    A `play` marks the video as watched, so it leaves future feeds. An `ended` removes
    the video from the watch queue.
    """
    event = watch_events.record_watch_event(
        session, body.video_id, body.event_type, body.position, body.duration
    )
    if body.event_type == "ended":
        queue.remove_video_from_queue(session, body.video_id)
    return event


class QueueAddInput(BaseModel):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$", description="YouTube video id")
    position: int | None = Field(
        default=None,
        ge=0,
        description="Where to insert it, 0 for next up; omitted or past the end: last",
    )


class QueueMoveInput(BaseModel):
    position: int = Field(ge=0, description="New 0-based position; past the end: last")


QUEUE_ITEM_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorDetail, "description": "No such queue item"}
}
QueueItemId = Annotated[int, Path(ge=1, description="Queue item id")]


@app.get("/queue", tags=["queue"])
def list_queue(session: SessionDep) -> list[queue.QueueItem]:
    """The watch queue in order, next up first."""
    return queue.list_queue(session)


@app.post(
    "/queue",
    tags=["queue"],
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": queue.QueueItem, "description": "Already queued"},
        404: {"model": ErrorDetail, "description": "The video doesn't exist or can't be watched"},
        502: {"model": ErrorDetail, "description": "YouTube could not be reached"},
    },
)
def add_to_queue(
    body: QueueAddInput, session: SessionDep, player: PlaybackDep, response: Response
) -> queue.QueueItem:
    """Add a video to the watch queue.

    A video whose metadata isn't stored yet is fetched from YouTube first (404 if it
    doesn't exist, 502 if YouTube can't be reached). Queueing a video again returns 200
    with its existing item, which keeps its place.
    """
    existing = queue.find_queued_video(session, body.video_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return existing
    if videos.get_stored_video(session, body.video_id) is None:
        try:
            videos.store_video(session, player.video(body.video_id))
        except GatewayError as error:
            raise _gateway_http_error(error) from error
    item, _ = queue.add_to_queue(session, body.video_id, body.position)
    return item


@app.patch("/queue/{item_id}", tags=["queue"], responses=QUEUE_ITEM_NOT_FOUND)
def move_queue_item(
    item_id: QueueItemId, body: QueueMoveInput, session: SessionDep
) -> list[queue.QueueItem]:
    """Move a queued video to a new position. Returns the whole queue in its new order."""
    if queue.move_queue_item(session, item_id, body.position) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Queue item not found")
    return queue.list_queue(session)


@app.delete(
    "/queue/{item_id}",
    tags=["queue"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses=QUEUE_ITEM_NOT_FOUND,
)
def remove_from_queue(item_id: QueueItemId, session: SessionDep) -> Response:
    """Remove a video from the watch queue."""
    if not queue.remove_from_queue(session, item_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Queue item not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.delete("/queue", tags=["queue"], status_code=status.HTTP_204_NO_CONTENT)
def clear_queue(session: SessionDep) -> Response:
    """Empty the watch queue."""
    queue.clear_queue(session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/history", tags=["watching"])
def search_history(
    session: SessionDep,
    q: Annotated[
        str | None,
        Query(
            max_length=history.HISTORY_QUERY_MAX_LENGTH,
            description="Only videos whose title or channel contains every word",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=history.MAX_HISTORY_LIMIT)] = (
        history.DEFAULT_HISTORY_LIMIT
    ),
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[history.HistoryEntry]:
    """Videos I've played, most recently watched first, each with where I left off."""
    return history.search_history(session, q, limit=limit, offset=offset)


@app.get(
    "/history/{video_id}",
    tags=["watching"],
    responses={404: {"model": ErrorDetail, "description": "The video was never played"}},
)
def get_history_entry(video_id: VideoId, session: SessionDep) -> history.HistoryEntry:
    """A video's history entry; `resume_position` is where the watch page picks up."""
    entry = history.get_history_entry(session, video_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not in the watch history")
    return entry


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


class KeywordMuteInput(BaseModel):
    keyword: str = Field(
        min_length=1,
        max_length=curation.KEYWORD_MAX_LENGTH,
        description="A word or phrase; videos whose title or description contain it "
        "(ignoring case) are left out of the feed",
    )


KEYWORD_MUTE_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorDetail, "description": "No such keyword mute"}
}
KeywordMuteId = Annotated[int, Path(ge=1, description="Keyword mute id")]


@app.get("/keyword-mutes", tags=["keyword-mutes"])
def list_keyword_mutes(session: SessionDep) -> list[curation.KeywordMute]:
    """All muted keywords, alphabetically."""
    return curation.list_keyword_mutes(session)


@app.post(
    "/keyword-mutes",
    tags=["keyword-mutes"],
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": curation.KeywordMute, "description": "Already muted"}},
)
def add_keyword_mute(
    body: KeywordMuteInput, session: SessionDep, response: Response
) -> curation.KeywordMute:
    """Mute a keyword.

    Muting a keyword again (in any case) returns 200 with the existing mute. A blank
    keyword is a 422 with a string `detail`.
    """
    try:
        mute, created = curation.add_keyword_mute(session, body.keyword)
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    if not created:
        response.status_code = status.HTTP_200_OK
    return mute


@app.patch(
    "/keyword-mutes/{mute_id}",
    tags=["keyword-mutes"],
    responses={
        **KEYWORD_MUTE_NOT_FOUND,
        409: {"model": ErrorDetail, "description": "Another mute has this keyword"},
    },
)
def update_keyword_mute(
    mute_id: KeywordMuteId, body: KeywordMuteInput, session: SessionDep
) -> curation.KeywordMute:
    """Change a muted keyword."""
    try:
        mute = curation.update_keyword_mute(session, mute_id, body.keyword)
    except curation.DuplicateKeywordMuteError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    if mute is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Keyword mute not found")
    return mute


@app.delete(
    "/keyword-mutes/{mute_id}",
    tags=["keyword-mutes"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses=KEYWORD_MUTE_NOT_FOUND,
)
def delete_keyword_mute(mute_id: KeywordMuteId, session: SessionDep) -> Response:
    """Unmute a keyword."""
    if not curation.delete_keyword_mute(session, mute_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Keyword mute not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class TierSimilarityOut(BaseModel):
    max: float = Field(description="Cosine similarity to the most similar video of the set")
    mean: float = Field(description="Mean cosine similarity to the videos of the set")
    nearest_video_id: str = Field(description="The video `max` is the similarity to")


class SimilarityFeaturesOut(BaseModel):
    """Similarity to the videos rated top tier (7.0 and up) and bottom tier (4.0 and
    down); a side is null when no video of that set has an embedding yet."""

    top_tier: TierSimilarityOut | None
    bottom_tier: TierSimilarityOut | None


TopicName = Annotated[
    str,
    Field(
        min_length=1,
        max_length=curation.TOPIC_NAME_MAX_LENGTH,
        description="A short label, unique ignoring case; it names the topic's boost "
        "in score breakdowns",
    ),
]
TopicDescription = Annotated[
    str,
    Field(
        min_length=1,
        max_length=curation.TOPIC_DESCRIPTION_MAX_LENGTH,
        description="What the topic is about, in plain language; videos similar to it "
        "are boosted (or suppressed)",
    ),
]
TopicWeight = Annotated[
    float,
    Field(
        ge=-1,
        le=1,
        description="-1 (suppress) to 1 (boost); a fully matching video gets this much "
        "added to its score",
    ),
]


class TopicInput(BaseModel):
    name: TopicName
    description: TopicDescription
    weight: TopicWeight
    decay: bool = Field(
        default=False,
        description=f"Halve the weight every {curation.TOPIC_HALF_LIFE_DAYS} days "
        "unless reaffirmed",
    )


class TopicUpdateInput(BaseModel):
    """Fields to change; omitted fields keep their current value."""

    name: TopicName | None = None
    description: TopicDescription | None = None
    weight: TopicWeight | None = None
    decay: bool | None = None


TOPIC_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorDetail, "description": "No such topic"}
}
TOPIC_NAME_TAKEN: dict[int | str, dict[str, Any]] = {
    409: {"model": ErrorDetail, "description": "Another topic has this name"}
}
TopicId = Annotated[int, Path(ge=1, description="Topic id")]


@app.get("/topics", tags=["topics"])
def list_topics(session: SessionDep) -> list[curation.Topic]:
    """All topics, alphabetically, with their current (decayed) weights."""
    return curation.list_topics(session)


@app.post(
    "/topics", tags=["topics"], status_code=status.HTTP_201_CREATED, responses=TOPIC_NAME_TAKEN
)
def add_topic(body: TopicInput, session: SessionDep, embedder: EmbedderDep) -> curation.Topic:
    """Create a topic; its description is embedded right away.

    A blank name or description is a 422 with a string `detail`.
    """
    try:
        return curation.add_topic(
            session,
            embedder,
            name=body.name,
            description=body.description,
            weight=body.weight,
            decay=body.decay,
        )
    except curation.DuplicateTopicError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error


@app.patch("/topics/{topic_id}", tags=["topics"], responses={**TOPIC_NOT_FOUND, **TOPIC_NAME_TAKEN})
def update_topic(
    topic_id: TopicId, body: TopicUpdateInput, session: SessionDep, embedder: EmbedderDep
) -> curation.Topic:
    """Change a topic. A new description is embedded again; setting the weight or turning
    decay on reaffirms the topic."""
    try:
        topic = curation.update_topic(
            session,
            embedder,
            topic_id,
            name=body.name,
            description=body.description,
            weight=body.weight,
            decay=body.decay,
        )
    except curation.DuplicateTopicError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    if topic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
    return topic


@app.post("/topics/{topic_id}/reaffirm", tags=["topics"], responses=TOPIC_NOT_FOUND)
def reaffirm_topic(topic_id: TopicId, session: SessionDep) -> curation.Topic:
    """Restart a decaying topic's decay, so its full weight applies again."""
    topic = curation.reaffirm_topic(session, topic_id)
    if topic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
    return topic


@app.delete(
    "/topics/{topic_id}",
    tags=["topics"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses=TOPIC_NOT_FOUND,
)
def delete_topic(topic_id: TopicId, session: SessionDep) -> Response:
    """Remove a topic."""
    if not curation.delete_topic(session, topic_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


SearchQuery = Annotated[
    str,
    Field(
        min_length=1,
        max_length=SEARCH_QUERY_MAX_LENGTH,
        description="What to search YouTube for",
    ),
]
SEARCH_ERRORS: dict[int | str, dict[str, Any]] = {
    502: {"model": ErrorDetail, "description": "YouTube could not be reached"}
}


@app.get("/search", tags=["search"], responses=SEARCH_ERRORS)
def search_videos(
    gateway: GatewayDep,
    q: Annotated[
        str,
        Query(min_length=1, max_length=SEARCH_QUERY_MAX_LENGTH, description="Search query"),
    ],
    sort: Annotated[SearchSort, Query(description="Result order")] = "relevance",
    upload_date: Annotated[
        SearchUploadDate | None, Query(description="Only videos uploaded within the last ...")
    ] = None,
    duration: Annotated[
        SearchDuration | None,
        Query(description="short: under 4 minutes, medium: 4-20 minutes, long: over 20"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_SEARCH_LIMIT)] = DEFAULT_SEARCH_LIMIT,
) -> list[SearchResult]:
    """Search YouTube for videos, in YouTube's order. A blank query is a 422 with a
    string `detail`."""
    filters = SearchFilters(sort=sort, upload_date=upload_date, duration=duration)
    try:
        return gateway.search(q, filters, limit=limit)
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except GatewayError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error


class SearchFiltersInput(BaseModel):
    sort: SearchSort = "relevance"
    upload_date: SearchUploadDate | None = Field(
        default=None, description="Only videos uploaded within the last ..."
    )
    duration: SearchDuration | None = Field(
        default=None, description="short: under 4 minutes, medium: 4-20 minutes, long: over 20"
    )

    def to_filters(self) -> SearchFilters:
        return SearchFilters(sort=self.sort, upload_date=self.upload_date, duration=self.duration)


class SavedSearchInput(BaseModel):
    query: SearchQuery
    filters: SearchFiltersInput = Field(default_factory=SearchFiltersInput)
    schedule: saved_searches.Schedule = Field(
        default=saved_searches.DEFAULT_SCHEDULE,
        description="How often its results are added to the candidates",
    )


class SavedSearchUpdateInput(BaseModel):
    """Fields to change; omitted fields keep their current value."""

    query: SearchQuery | None = None
    filters: SearchFiltersInput | None = None
    schedule: saved_searches.Schedule | None = None


SAVED_SEARCH_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorDetail, "description": "No such saved search"}
}
SavedSearchId = Annotated[int, Path(ge=1, description="Saved search id")]


@app.get("/saved-searches", tags=["saved-searches"])
def list_saved_searches(session: SessionDep) -> list[saved_searches.SavedSearch]:
    """All saved searches, alphabetically by query."""
    return saved_searches.list_saved_searches(session)


@app.post(
    "/saved-searches",
    tags=["saved-searches"],
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": saved_searches.SavedSearch, "description": "Already saved"}},
)
def add_saved_search(
    body: SavedSearchInput, session: SessionDep, response: Response
) -> saved_searches.SavedSearch:
    """Save a search; its results are added to the candidates on its schedule.

    Saving the same query (in any case) with the same filters again returns 200 with the
    existing search. A blank query is a 422 with a string `detail`.
    """
    try:
        search, created = saved_searches.add_saved_search(
            session, body.query, body.filters.to_filters(), schedule=body.schedule
        )
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    if not created:
        response.status_code = status.HTTP_200_OK
    return search


@app.patch(
    "/saved-searches/{search_id}",
    tags=["saved-searches"],
    responses={
        **SAVED_SEARCH_NOT_FOUND,
        409: {"model": ErrorDetail, "description": "Another saved search is the same"},
    },
)
def update_saved_search(
    search_id: SavedSearchId, body: SavedSearchUpdateInput, session: SessionDep
) -> saved_searches.SavedSearch:
    """Change a saved search's query, filters or schedule. A new query or filters
    make it run with the next candidate run."""
    try:
        search = saved_searches.update_saved_search(
            session,
            search_id,
            query=body.query,
            filters=body.filters.to_filters() if body.filters is not None else None,
            schedule=body.schedule,
        )
    except saved_searches.DuplicateSavedSearchError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    if search is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved search not found")
    return search


@app.delete(
    "/saved-searches/{search_id}",
    tags=["saved-searches"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses=SAVED_SEARCH_NOT_FOUND,
)
def delete_saved_search(search_id: SavedSearchId, session: SessionDep) -> Response:
    """Delete a saved search. Candidates it already found stay."""
    if not saved_searches.delete_saved_search(session, search_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved search not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


PlaylistName = Annotated[
    str, Field(min_length=1, max_length=playlists.NAME_MAX_LENGTH, description="Playlist name")
]
PlaylistDescription = Annotated[str, Field(max_length=playlists.DESCRIPTION_MAX_LENGTH)]


class PlaylistInput(BaseModel):
    name: PlaylistName
    description: PlaylistDescription = ""


class PlaylistUpdateInput(BaseModel):
    """Fields to change; omitted fields keep their current value."""

    name: PlaylistName | None = None
    description: PlaylistDescription | None = None


class PlaylistItemInput(BaseModel):
    position: int | None = Field(
        default=None, ge=0, description="0-based place to insert at; omitted: at the end"
    )


class PlaylistItemMoveInput(BaseModel):
    position: int = Field(ge=0, description="0-based place to move to (clamped to the end)")


class PlaylistDetail(BaseModel):
    playlist: playlists.Playlist
    items: list[playlists.PlaylistItem] = Field(description="The playlist's videos, in order")


PLAYLIST_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorDetail, "description": "No such playlist"}
}
PLAYLIST_NAME_TAKEN: dict[int | str, dict[str, Any]] = {
    409: {"model": ErrorDetail, "description": "Another playlist has this name"}
}
PlaylistId = Annotated[int, Path(ge=1, description="Playlist id")]


@app.get("/playlists", tags=["playlists"])
def list_playlists(
    session: SessionDep,
    video_id: Annotated[
        str | None,
        Query(
            pattern=r"^[A-Za-z0-9_-]{11}$",
            description="Fill each playlist's `contains_video` for this video",
        ),
    ] = None,
) -> list[playlists.Playlist]:
    """All local playlists, alphabetically by name."""
    return playlists.list_playlists(session, video_id=video_id)


@app.post(
    "/playlists",
    tags=["playlists"],
    status_code=status.HTTP_201_CREATED,
    responses=PLAYLIST_NAME_TAKEN,
)
def create_playlist(body: PlaylistInput, session: SessionDep) -> playlists.Playlist:
    """Create an empty playlist. A blank name is a 422 with a string `detail`."""
    try:
        return playlists.create_playlist(session, body.name, body.description)
    except playlists.DuplicatePlaylistError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error


@app.get("/playlists/{playlist_id}", tags=["playlists"], responses=PLAYLIST_NOT_FOUND)
def get_playlist(playlist_id: PlaylistId, session: SessionDep) -> PlaylistDetail:
    """A playlist and its videos, in order. Videos whose details aren't stored yet have
    null titles."""
    playlist = playlists.get_playlist(session, playlist_id)
    items = playlists.list_items(session, playlist_id)
    if playlist is None or items is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist not found")
    return PlaylistDetail(playlist=playlist, items=items)


@app.patch(
    "/playlists/{playlist_id}",
    tags=["playlists"],
    responses={**PLAYLIST_NOT_FOUND, **PLAYLIST_NAME_TAKEN},
)
def update_playlist(
    playlist_id: PlaylistId, body: PlaylistUpdateInput, session: SessionDep
) -> playlists.Playlist:
    """Rename a playlist or change its description."""
    try:
        playlist = playlists.update_playlist(
            session, playlist_id, name=body.name, description=body.description
        )
    except playlists.DuplicatePlaylistError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    if playlist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist not found")
    return playlist


@app.delete(
    "/playlists/{playlist_id}",
    tags=["playlists"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses=PLAYLIST_NOT_FOUND,
)
def delete_playlist(playlist_id: PlaylistId, session: SessionDep) -> Response:
    """Delete a playlist and its items (the videos themselves stay)."""
    if not playlists.delete_playlist(session, playlist_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.put(
    "/playlists/{playlist_id}/items/{video_id}",
    tags=["playlists"],
    status_code=status.HTTP_201_CREATED,
    responses={
        **PLAYLIST_NOT_FOUND,
        200: {"model": playlists.PlaylistItem, "description": "Already in the playlist"},
    },
)
def add_playlist_item(
    playlist_id: PlaylistId,
    video_id: VideoId,
    session: SessionDep,
    response: Response,
    body: PlaylistItemInput | None = None,
) -> playlists.PlaylistItem:
    """Add a video to a playlist, at the end or at `position`. Adding a video that is
    already there returns 200 and leaves it where it is."""
    try:
        result = playlists.add_item(
            session, playlist_id, video_id, position=body.position if body else None
        )
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist not found")
    item, created = result
    if not created:
        response.status_code = status.HTTP_200_OK
    return item


@app.patch(
    "/playlists/{playlist_id}/items/{video_id}",
    tags=["playlists"],
    responses={404: {"model": ErrorDetail, "description": "The video isn't in the playlist"}},
)
def move_playlist_item(
    playlist_id: PlaylistId, video_id: VideoId, body: PlaylistItemMoveInput, session: SessionDep
) -> playlists.PlaylistItem:
    """Move a video to another place in its playlist, shifting the videos in between."""
    item = playlists.move_item(session, playlist_id, video_id, body.position)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not in playlist")
    return item


@app.delete(
    "/playlists/{playlist_id}/items/{video_id}",
    tags=["playlists"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorDetail, "description": "The video isn't in the playlist"}},
)
def remove_playlist_item(
    playlist_id: PlaylistId, video_id: VideoId, session: SessionDep
) -> Response:
    """Take a video out of a playlist."""
    if not playlists.remove_item(session, playlist_id, video_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not in playlist")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ScoreBreakdownOut(BaseModel):
    """How an item's score was made:
    `alpha * model + channel + similarity + sum(topics) = final`."""

    model: float
    alpha: float
    channel: float
    similarity: float = Field(
        description="Closeness to top-tier rated videos minus closeness to bottom-tier ones"
    )
    topics: dict[str, float] = Field(
        description="Boost (or suppression) per topic name; only topics that matched"
    )
    final: float
    similarity_features: SimilarityFeaturesOut | None = Field(
        description="What `similarity` was computed from; null for unenriched videos"
    )


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
    watched: bool = Field(description="Whether the video has been played here or rated")


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
        items=[_feed_item_out(item) for item in feed.items],
    )


def _feed_item_out(item: feeds.FeedItem) -> FeedItemOut:
    return FeedItemOut.model_validate({**vars(item), "breakdown": item.breakdown.to_dict()})


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


class DismissInput(BaseModel):
    reason: str | None = Field(
        default=None,
        max_length=feeds.DISMISS_REASON_MAX_LENGTH,
        description='Why the item was dismissed, e.g. "Not interested"; blank means none',
    )


FEED_ITEM_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorDetail, "description": "No such feed item"}
}
FeedItemId = Annotated[int, Path(ge=1, description="Feed item id")]


@app.post("/feed-items/{item_id}/dismiss", tags=["feed"], responses=FEED_ITEM_NOT_FOUND)
def dismiss_feed_item(
    item_id: FeedItemId, session: SessionDep, body: DismissInput | None = None
) -> FeedItemOut:
    """Dismiss a feed item, with an optional reason.

    The video is left out of every feed built afterwards and counts as a weak negative
    signal. Dismissing again keeps the first `dismissed_at`; a new reason replaces the
    old one.
    """
    try:
        item = feeds.dismiss_feed_item(session, item_id, body.reason if body else None)
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feed item not found")
    return _feed_item_out(item)


@app.post("/feed/refresh", tags=["feed"])
def refresh_feed(poll: FeedPollDep) -> FeedOut:
    """Poll due subscriptions, then build and store a new feed for today.

    A failed poll doesn't fail the refresh; the feed is built from stored candidates.
    """
    return _feed_out(feeds.refresh_feed(poll=poll))


class ScoreCountOut(BaseModel):
    score: int = Field(ge=1, le=10, description="Whole score; 6.5 to 7.4 count as 7")
    count: int


class ScoreShareOut(BaseModel):
    """Where shown items' scores came from: shares of the summed absolute size of each
    kind of score term. They sum to 1."""

    model: float = Field(description="`alpha * model`, the trained model's blended prediction")
    curation: float = Field(description="`channel` and `topics`: your channel priors and topics")
    similarity: float = Field(
        description="Closeness to top- and bottom-tier rated videos (rules-based, learned "
        "from ratings rather than set by you)"
    )


class WeekInsightsOut(BaseModel):
    week_start: dt.date = Field(description="Monday of the week (local date)")
    rated_count: int = Field(description="Videos first rated this week")
    good_count: int = Field(description="Of those, how many are rated 5.5 or higher")
    good_rate: float | None = Field(
        description="good_count / rated_count; null when nothing was rated"
    )
    score_counts: list[ScoreCountOut] = Field(
        description="Ratings of the week per whole score, best (10) first"
    )
    shown_count: int = Field(
        description="Distinct videos in the week's feeds (the latest feed of each date)"
    )
    shown_rated_count: int = Field(description="Of those, how many have been rated")
    rating_rate: float | None = Field(
        description="shown_rated_count / shown_count; null when no feed was built"
    )
    feed_count: int = Field(description="Dates in the week with a feed")
    model_feed_count: int = Field(description="Of those, feeds the trained model contributed to")
    score_share: ScoreShareOut | None = Field(
        description="Model vs curation share of the shown items' scores; null when "
        "nothing was shown"
    )


class WeeklyInsightsOut(BaseModel):
    good_threshold: float = Field(description="The lowest score counted as good")
    weeks: list[WeekInsightsOut] = Field(description="Oldest first, ending with this week")


@app.get("/insights/weekly", tags=["insights"])
def get_weekly_insights(
    session: SessionDep,
    weeks: Annotated[
        int, Query(ge=1, le=insights.MAX_WEEKS, description="How many weeks, up to this one")
    ] = insights.DEFAULT_WEEKS,
) -> WeeklyInsightsOut:
    """Whether the feed is working, week by week: the good rate (the success
    metric), score distribution, rating rate and model vs curation share."""
    return WeeklyInsightsOut(
        good_threshold=scores.GOOD_THRESHOLD,
        weeks=[
            WeekInsightsOut.model_validate(week, from_attributes=True)
            for week in insights.weekly_insights(session, weeks=weeks)
        ],
    )


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


class SponsorSegmentOut(BaseModel):
    id: str = Field(description="SponsorBlock's UUID for the segment")
    category: str = Field(description='SponsorBlock category, e.g. "sponsor" or "selfpromo"')
    start_seconds: float
    end_seconds: float


@app.get(
    "/videos/{video_id}/segments",
    tags=["videos"],
    responses={502: {"model": ErrorDetail, "description": "SponsorBlock could not be reached"}},
)
def get_sponsor_segments(video_id: VideoId, player: PlaybackDep) -> list[SponsorSegmentOut]:
    """The video's SponsorBlock segments for the player to skip, by start time.

    Only the categories in `SPONSORBLOCK_CATEGORIES` are listed; empty when the video
    has none (or skipping is off).
    """
    try:
        segments = player.sponsor_segments(video_id)
    except sponsorblock.SponsorBlockError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    return [SponsorSegmentOut.model_validate(vars(segment)) for segment in segments]


class CommentOut(BaseModel):
    id: str
    text: str
    author: str = Field(description="Display name, usually the author's @handle")
    author_channel_id: str | None
    author_thumbnail_url: str | None
    author_is_uploader: bool
    like_count: int | None
    published_at: str | None = Field(
        description="Estimated from YouTube's relative time (`published_text`), ISO 8601 UTC"
    )
    published_text: str | None = Field(description='As YouTube shows it, e.g. "2 years ago"')
    is_pinned: bool
    is_hearted: bool = Field(description="Hearted by the uploader")


@app.get("/videos/{video_id}/comments", tags=["videos"], responses=VIDEO_ERRORS)
def get_comments(
    video_id: VideoId,
    gateway: GatewayDep,
    limit: Annotated[int, Query(ge=1, le=MAX_COMMENTS_LIMIT)] = DEFAULT_COMMENTS_LIMIT,
) -> list[CommentOut]:
    """The video's top comments (pinned first), without replies, fetched from YouTube on
    every call. Empty when comments are off."""
    try:
        comments = gateway.get_comments(video_id, limit=limit)
    except GatewayError as error:
        raise _gateway_http_error(error) from error
    return [
        CommentOut.model_validate(
            {
                **vars(comment),
                "published_at": (
                    format_timestamp(comment.published_at)
                    if comment.published_at is not None
                    else None
                ),
            }
        )
        for comment in comments
    ]


class ModelVersionOut(BaseModel):
    id: int
    kind: ranking_models.ModelKind = Field(
        description="lightgbm once there are enough ratings, else the ridge fallback"
    )
    feature_version: int
    compatible: bool = Field(
        description="Trained with the current features; only compatible versions can be activated"
    )
    spearman: float | None = Field(
        description="Spearman correlation on the holdout ratings; null when undefined"
    )
    mae: float = Field(description="Mean absolute error on the holdout ratings")
    metrics: dict[str, Any] = Field(description="The full training report")
    created_at: str = Field(description="When it was trained, ISO 8601 UTC")
    active: bool = Field(description="Whether it ranks the next feed")
    activated_at: str | None = Field(description="When it was last activated, ISO 8601 UTC")


def _model_version_out(version: ranking_models.ModelVersion) -> ModelVersionOut:
    return ModelVersionOut(
        id=version.id,
        kind=version.kind,
        feature_version=version.feature_version,
        compatible=version.compatible,
        spearman=version.spearman,
        mae=version.mae,
        metrics=version.metrics,
        created_at=version.created_at,
        active=version.active,
        activated_at=version.activated_at,
    )


ModelVersionId = Annotated[int, Path(ge=1, description="Model version id")]


@app.get("/models", tags=["models"])
def list_models(session: SessionDep) -> list[ModelVersionOut]:
    """The stored ranking model versions (the last 10 trained), newest first."""
    return [_model_version_out(v) for v in ranking_models.list_model_versions(session)]


@app.post(
    "/models/{version_id}/activate",
    tags=["models"],
    responses={
        404: {"model": ErrorDetail, "description": "No such model version"},
        409: {
            "model": ErrorDetail,
            "description": "The version was trained with other features than the current ones",
        },
    },
)
def activate_model(version_id: ModelVersionId, session: SessionDep) -> ModelVersionOut:
    """Make a model version the active one, e.g. to roll back to an earlier version.

    The next feed built is ranked with it; feeds already built keep their order.
    """
    try:
        version = ranking_models.activate(session, version_id)
    except ranking_models.IncompatibleModelError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model version not found")
    return _model_version_out(version)


# Channel graph and discovery

CHANNEL_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorDetail, "description": "The channel doesn't exist"},
    502: {"model": ErrorDetail, "description": "YouTube could not be reached"},
}


@app.get("/channels/{channel_id}/featured", tags=["discovery"], responses=CHANNEL_ERRORS)
def get_featured_channels(
    channel_id: ChannelId, session: SessionDep, gateway: GatewayDep
) -> list[channel_graph.GraphChannel]:
    """The channels a channel features on its page, in its order, with whether I'm
    subscribed to each. Kept for a week; a stale copy is served when YouTube fails."""
    try:
        return channel_graph.featured_channels(session, gateway, channel_id)
    except GatewayError as error:
        raise _gateway_http_error(error) from error


class ChannelSummaryOut(BaseModel):
    channel_id: str
    title: str
    handle: str | None
    url: str | None
    thumbnail_url: str | None
    subscribed: bool


class UploadOut(BaseModel):
    id: str
    title: str
    duration_seconds: int | None
    view_count: int | None
    thumbnail_url: str | None
    published_at: str | None = Field(description="Upload time, ISO 8601 UTC, when listed")
    live_status: str | None


class ChannelUploadsOut(BaseModel):
    channel: ChannelSummaryOut
    videos: list[UploadOut] = Field(description="Newest first")


@app.get("/channels/{channel_id}/uploads", tags=["discovery"], responses=CHANNEL_ERRORS)
def get_channel_uploads(
    channel_id: ChannelId,
    session: SessionDep,
    gateway: GatewayDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
) -> ChannelUploadsOut:
    """A channel and its most recent uploads, newest first, straight from YouTube."""
    try:
        uploads = gateway.get_channel_uploads(channel_id, limit=limit)
    except GatewayError as error:
        raise _gateway_http_error(error) from error
    channel = uploads.channel
    return ChannelUploadsOut(
        channel=ChannelSummaryOut(
            channel_id=channel.id,
            title=channel.title,
            handle=channel.handle,
            url=channel.url,
            thumbnail_url=channel.thumbnail_url,
            subscribed=curation.get_channel(session, channel.id) is not None,
        ),
        videos=[
            UploadOut(
                id=video.id,
                title=video.title,
                duration_seconds=video.duration_seconds,
                view_count=video.view_count,
                thumbnail_url=video.thumbnail_url,
                published_at=(format_timestamp(video.published_at) if video.published_at else None),
                live_status=video.live_status,
            )
            for video in uploads.videos
        ],
    )


@app.get("/discover/suggested-channels", tags=["discovery"])
def get_suggested_channels(
    gateway: GatewayDep, limit: Annotated[int, Query(ge=1, le=50)] = 20
) -> list[channel_graph.SuggestedChannel]:
    """Channels featured by channels I like (loved or liked subscriptions, channels of
    top-tier rated videos) that I'm not subscribed to, most often featured first.

    Liked channels whose featured channels were never fetched are fetched first (a few
    per request); the daily feed job keeps the rest fresh.
    """
    return channel_graph.suggest(get_session_factory(), gateway, limit=limit)


class ExternalSourceInput(BaseModel):
    kind: external_sources.Kind = Field(
        description="subreddit (its hot posts), rss (an RSS or Atom feed) or page (a web "
        "page whose links are read)"
    )
    url: str = Field(
        min_length=1,
        max_length=external_sources.URL_MAX_LENGTH,
        description='The feed or page URL; for a subreddit, "r/name", "name" or a Reddit link',
    )
    schedule: external_sources.Schedule = Field(
        default=external_sources.DEFAULT_SCHEDULE, description="How often to fetch it"
    )


class ExternalSourceUpdateInput(BaseModel):
    """Fields to change; omitted fields keep their current value."""

    schedule: external_sources.Schedule | None = None


EXTERNAL_SOURCE_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorDetail, "description": "No such external source"}
}
ExternalSourceId = Annotated[int, Path(ge=1, description="External source id")]


@app.get("/external-sources", tags=["external-sources"])
def list_external_sources(session: SessionDep) -> list[external_sources.ExternalSource]:
    """All external sources (subreddits, feeds, link pages) with their fetch status."""
    return external_sources.list_sources(session)


@app.post(
    "/external-sources",
    tags=["external-sources"],
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": external_sources.ExternalSource, "description": "Already added"}},
)
def add_external_source(
    body: ExternalSourceInput, session: SessionDep, response: Response
) -> external_sources.ExternalSource:
    """Add a subreddit, feed or link page; it is fetched on the worker's next check.

    Adding a URL again returns 200 with the existing source. A URL that can't be a source
    of that kind (including any YouTube link) is a 422 with a string `detail`.
    """
    try:
        source, created = external_sources.add_source(session, body.kind, body.url, body.schedule)
    except external_sources.InvalidSourceError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    if not created:
        response.status_code = status.HTTP_200_OK
    return source


@app.patch(
    "/external-sources/{source_id}",
    tags=["external-sources"],
    responses=EXTERNAL_SOURCE_NOT_FOUND,
)
def update_external_source(
    source_id: ExternalSourceId, body: ExternalSourceUpdateInput, session: SessionDep
) -> external_sources.ExternalSource:
    """Change how often a source is fetched."""
    source = external_sources.update_source(session, source_id, schedule=body.schedule)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "External source not found")
    return source


@app.delete(
    "/external-sources/{source_id}",
    tags=["external-sources"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses=EXTERNAL_SOURCE_NOT_FOUND,
)
def delete_external_source(source_id: ExternalSourceId, session: SessionDep) -> Response:
    """Remove a source. Videos it already found stay candidates."""
    if not external_sources.delete_source(session, source_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "External source not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    "/import/takeout",
    tags=["import"],
    responses={
        413: {"model": ErrorDetail, "description": "The file is too large"},
        422: {"model": ErrorDetail, "description": "The file isn't a Takeout watch history"},
    },
)
def import_takeout(
    file: Annotated[
        UploadFile,
        File(description="Takeout `watch-history.json` or `watch-history.html`"),
    ],
    session: SessionDep,
    subscribe_min_watches: Annotated[
        int | None,
        Form(ge=1, description="Subscribe to channels watched at least this often; unset: none"),
    ] = None,
    max_candidates: Annotated[
        int,
        Form(ge=0, le=10_000, description="Most recently watched videos added as candidates"),
    ] = importer.DEFAULT_MAX_CANDIDATES,
) -> importer.ImportReport:
    """Import a Google Takeout YouTube watch history (JSON or HTML).

    Seeds channels, videos and candidates (source `takeout`), and optionally subscribes to
    often-watched channels. Never creates ratings or watch events. Each entry is counted
    as imported, removed (deleted or private video), malformed or skipped (e.g. ads).
    """
    content = file.file.read(importer.MAX_TAKEOUT_BYTES + 1)
    if len(content) > importer.MAX_TAKEOUT_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"The file is larger than {importer.MAX_TAKEOUT_BYTES // (1024 * 1024)} MB",
        )
    try:
        return importer.import_takeout(
            session,
            content,
            subscribe_min_watches=subscribe_min_watches,
            max_candidates=max_candidates,
        )
    except importer.TakeoutFormatError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error


@app.get(
    "/export",
    tags=["export"],
    response_class=Response,
    responses={
        200: {
            "description": "Everything as one JSON document, sent as a file download",
            "content": {"application/json": {"schema": {"type": "object"}}},
        }
    },
)
def export_all(session: SessionDep) -> Response:
    """Download all data as JSON: ratings, curation, feeds, library, models and settings.

    See `homefeed_core.exporter` for the document's shape. Derived data (embeddings,
    tags, the candidate pool) is left out, as are secrets and file paths.
    """
    data = exporter.export_data(session)
    filename = f"homefeed-export-{data['exported_at'][:10]}.json"
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
