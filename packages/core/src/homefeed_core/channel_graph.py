"""The channel graph: channels featured by the channels I like, as suggestions and as a
candidate source.

A channel's featured channels (the "Featured channels" shelf on its page) are fetched
through the Gateway and stored in `featured_channels`, with the fetch time in
`channel_graph_fetches`; they are refetched once older than `FEATURED_MAX_AGE`.

Liked channels are the subscribed, unmuted channels with a love or like prior, then the
channels of videos rated top tier (A-- and up), and never a muted channel. Their
featured channels that I'm not subscribed to are the suggested channels, ordered by how
many liked channels feature them. `ChannelGraphSource` turns the top suggestions'
newest uploads into candidates, attributed to the liked channel that featured them.
"""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.candidates import CHANNEL_GRAPH, FoundVideo
from homefeed_core.gateway import FeaturedChannel, Gateway, GatewayError
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.grades import GRADES, is_top_tier

logger = logging.getLogger(__name__)

# Featured channels change rarely; refetch a channel's after this long.
FEATURED_MAX_AGE = timedelta(days=7)
# At most this many liked channels' featured channels are fetched per run or request.
DEFAULT_MAX_SEEDS = 20
DEFAULT_SUGGESTIONS_LIMIT = 20


@dataclass(frozen=True)
class ChannelRef:
    channel_id: str
    title: str


@dataclass(frozen=True)
class GraphChannel:
    """A channel another channel features, and whether I'm subscribed to it."""

    channel_id: str
    title: str
    handle: str | None
    url: str | None
    thumbnail_url: str | None
    subscriber_count: int | None
    subscribed: bool


@dataclass(frozen=True)
class SuggestedChannel:
    """A channel featured by channels I like, which I'm not subscribed to."""

    channel_id: str
    title: str
    handle: str | None
    url: str | None
    thumbnail_url: str | None
    subscriber_count: int | None
    featured_by: list[ChannelRef]  # the liked channels featuring it, in liked order


# Liked channels


def liked_channel_ids(session: Session, *, limit: int | None = None) -> list[str]:
    """Channels I like: loved, then liked subscriptions (by title), then channels of
    top-tier rated videos (most recently rated first). Muted channels never count."""
    rows = session.execute(
        text(
            """
            WITH liked AS (
                SELECT p.channel_id AS id,
                       CASE p.prior WHEN 'love' THEN 0 ELSE 1 END AS rank,
                       c.title COLLATE NOCASE AS sort_key
                FROM channel_prefs AS p JOIN channels AS c ON c.id = p.channel_id
                WHERE p.prior IN ('love', 'like') AND p.muted = 0
                UNION ALL
                SELECT v.channel_id, 2, NULL
                FROM ratings AS r JOIN videos AS v ON v.id = r.video_id
                WHERE r.grade IN :grades
                GROUP BY v.channel_id
            ),
            last_rated AS (
                SELECT v.channel_id AS id, max(r.rated_at) AS rated_at
                FROM ratings AS r JOIN videos AS v ON v.id = r.video_id
                WHERE r.grade IN :grades
                GROUP BY v.channel_id
            )
            SELECT liked.id
            FROM liked LEFT JOIN last_rated ON last_rated.id = liked.id
            WHERE liked.id NOT IN (SELECT channel_id FROM channel_prefs WHERE muted = 1)
            GROUP BY liked.id
            ORDER BY min(liked.rank), min(liked.sort_key), max(last_rated.rated_at) DESC,
                     liked.id
            LIMIT :limit
            """
        ).bindparams(bindparam("grades", expanding=True)),
        {
            "grades": [grade for grade in GRADES if is_top_tier(grade)],
            "limit": -1 if limit is None else limit,
        },
    )
    return list(rows.scalars())


# Storage


def store_featured(
    session: Session,
    channel_id: str,
    featured: Sequence[FeaturedChannel],
    *,
    now: datetime | None = None,
) -> None:
    """Replace the stored featured channels of `channel_id` (which must be in
    `channels`) and mark them fetched. Featured channels are upserted into `channels`."""
    for channel in featured:
        session.execute(
            text(
                """
                INSERT INTO channels (id, title, handle, url, thumbnail_url)
                VALUES (:id, :title, :handle, :url, :thumbnail_url)
                ON CONFLICT (id) DO UPDATE SET
                    title = coalesce(nullif(excluded.title, ''), channels.title),
                    handle = coalesce(excluded.handle, channels.handle),
                    url = coalesce(excluded.url, channels.url),
                    thumbnail_url = coalesce(excluded.thumbnail_url, channels.thumbnail_url),
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """
            ),
            {
                "id": channel.id,
                "title": channel.title,
                "handle": channel.handle,
                "url": channel.url,
                "thumbnail_url": channel.thumbnail_url,
            },
        )
    session.execute(
        text(
            """
            INSERT INTO channel_graph_fetches (channel_id, fetched_at)
            VALUES (:id, coalesce(:at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))
            ON CONFLICT (channel_id) DO UPDATE SET fetched_at = excluded.fetched_at
            """
        ),
        {"id": channel_id, "at": format_timestamp(now) if now is not None else None},
    )
    session.execute(
        text("DELETE FROM featured_channels WHERE channel_id = :id"), {"id": channel_id}
    )
    rows = [
        {
            "channel_id": channel_id,
            "featured_id": channel.id,
            "position": position,
            "subscriber_count": channel.subscriber_count,
        }
        for position, channel in enumerate(featured)
        if channel.id != channel_id
    ]
    if rows:
        session.execute(
            text(
                """
                INSERT INTO featured_channels (channel_id, featured_id, position,
                                               subscriber_count)
                VALUES (:channel_id, :featured_id, :position, :subscriber_count)
                ON CONFLICT (channel_id, featured_id) DO NOTHING
                """
            ),
            rows,
        )


def stored_featured(session: Session, channel_id: str) -> list[GraphChannel] | None:
    """The stored featured channels of `channel_id` in page order, or None if they were
    never fetched."""
    fetched = session.execute(
        text("SELECT 1 FROM channel_graph_fetches WHERE channel_id = :id"), {"id": channel_id}
    ).first()
    if fetched is None:
        return None
    rows = session.execute(
        text(
            """
            SELECT c.id, c.title, c.handle, c.url, c.thumbnail_url, f.subscriber_count,
                   EXISTS (SELECT 1 FROM channel_prefs AS p WHERE p.channel_id = c.id)
            FROM featured_channels AS f JOIN channels AS c ON c.id = f.featured_id
            WHERE f.channel_id = :id
            ORDER BY f.position, c.id
            """
        ),
        {"id": channel_id},
    )
    return [GraphChannel(*row[:6], subscribed=bool(row[6])) for row in rows]


def stale_channel_ids(
    session: Session,
    channel_ids: Iterable[str],
    *,
    max_age: timedelta = FEATURED_MAX_AGE,
    now: datetime | None = None,
) -> list[str]:
    """Those of `channel_ids` whose featured channels were never fetched or are older
    than `max_age`, in input order."""
    ids = list(dict.fromkeys(channel_ids))
    if not ids:
        return []
    cutoff = format_timestamp((now or datetime.now(UTC)) - max_age)
    fresh = set(
        session.execute(
            text(
                "SELECT channel_id FROM channel_graph_fetches "
                "WHERE channel_id IN :ids AND fetched_at > :cutoff"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": ids, "cutoff": cutoff},
        ).scalars()
    )
    return [channel_id for channel_id in ids if channel_id not in fresh]


@dataclass(frozen=True)
class RefreshReport:
    refreshed: list[str]
    failed: dict[str, GatewayError]


def refresh(
    sessions: sessionmaker[Session],
    gateway: Gateway,
    channel_ids: Iterable[str],
    *,
    max_age: timedelta = FEATURED_MAX_AGE,
    now: datetime | None = None,
) -> RefreshReport:
    """Fetch and store the featured channels of those `channel_ids` that are stale.
    A channel whose fetch fails is logged and reported, keeping what was stored."""
    with sessions() as session:
        stale = stale_channel_ids(session, channel_ids, max_age=max_age, now=now)
    refreshed: list[str] = []
    failed: dict[str, GatewayError] = {}
    for channel_id in stale:
        try:
            featured = gateway.get_featured_channels(channel_id)
        except GatewayError as error:
            logger.warning("Could not fetch featured channels of %s: %s", channel_id, error)
            failed[channel_id] = error
            continue
        with sessions.begin() as session:
            store_featured(session, channel_id, featured, now=now)
        refreshed.append(channel_id)
    return RefreshReport(refreshed, failed)


# Reading the graph


def featured_channels(
    session: Session,
    gateway: Gateway,
    channel_id: str,
    *,
    max_age: timedelta = FEATURED_MAX_AGE,
    now: datetime | None = None,
) -> list[GraphChannel]:
    """The channels `channel_id` features, from storage while fresh, else through the
    Gateway (and stored when the channel is known). When the Gateway fails, a stale
    stored copy is returned; without one, its error is raised."""
    stored = stored_featured(session, channel_id)
    if stored is not None and not stale_channel_ids(
        session, [channel_id], max_age=max_age, now=now
    ):
        return stored
    try:
        featured = gateway.get_featured_channels(channel_id)
    except GatewayError:
        if stored is not None:
            return stored
        raise
    known = session.execute(
        text("SELECT 1 FROM channels WHERE id = :id"), {"id": channel_id}
    ).first()
    if known is not None:
        store_featured(session, channel_id, featured, now=now)
        result = stored_featured(session, channel_id)
        assert result is not None
        return result
    subscribed = _subscribed_ids(session, [channel.id for channel in featured])
    return [
        GraphChannel(
            channel_id=channel.id,
            title=channel.title,
            handle=channel.handle,
            url=channel.url,
            thumbnail_url=channel.thumbnail_url,
            subscriber_count=channel.subscriber_count,
            subscribed=channel.id in subscribed,
        )
        for channel in featured
    ]


def suggested_channels(
    session: Session, *, limit: int | None = DEFAULT_SUGGESTIONS_LIMIT
) -> list[SuggestedChannel]:
    """Channels featured by liked channels (from storage) that I'm not subscribed to,
    most often featured first, then by best position on a page, then most subscribers."""
    liked = liked_channel_ids(session)
    if not liked:
        return []
    order = {channel_id: index for index, channel_id in enumerate(liked)}
    rows = session.execute(
        text(
            """
            SELECT f.featured_id, f.channel_id, f.position, f.subscriber_count,
                   c.title, c.handle, c.url, c.thumbnail_url, src.title
            FROM featured_channels AS f
            JOIN channels AS c ON c.id = f.featured_id
            JOIN channels AS src ON src.id = f.channel_id
            WHERE f.channel_id IN :liked
              AND f.featured_id NOT IN (SELECT channel_id FROM channel_prefs)
            """
        ).bindparams(bindparam("liked", expanding=True)),
        {"liked": liked},
    )
    by_id: dict[str, list[tuple[int, int, int | None, ChannelRef]]] = {}
    details: dict[str, tuple[str, str | None, str | None, str | None]] = {}
    for featured_id, source_id, position, subscribers, title, handle, url, thumb, source in rows:
        by_id.setdefault(featured_id, []).append(
            (order[source_id], position, subscribers, ChannelRef(source_id, source))
        )
        details[featured_id] = (title, handle, url, thumb)
    suggestions: list[tuple[tuple[int, int, int, str, str], SuggestedChannel]] = []
    for featured_id, edges in by_id.items():
        edges.sort(key=lambda edge: (edge[0], edge[1]))
        title, handle, url, thumb = details[featured_id]
        subscribers = max((edge[2] for edge in edges if edge[2] is not None), default=None)
        suggestion = SuggestedChannel(
            channel_id=featured_id,
            title=title,
            handle=handle,
            url=url,
            thumbnail_url=thumb,
            subscriber_count=subscribers,
            featured_by=[edge[3] for edge in edges],
        )
        key = (
            -len(edges),
            min(edge[1] for edge in edges),
            -(subscribers or 0),
            title.casefold(),
            featured_id,
        )
        suggestions.append((key, suggestion))
    suggestions.sort(key=lambda pair: pair[0])
    ranked = [suggestion for _key, suggestion in suggestions]
    return ranked if limit is None else ranked[:limit]


def suggest(
    sessions: sessionmaker[Session],
    gateway: Gateway,
    *,
    limit: int | None = DEFAULT_SUGGESTIONS_LIMIT,
    max_fetches: int = 5,
    now: datetime | None = None,
) -> list[SuggestedChannel]:
    """`suggested_channels`, first fetching the featured channels of up to
    `max_fetches` liked channels that were never fetched (the daily job keeps the rest
    fresh), so new likes show their suggestions right away."""
    with sessions() as session:
        liked = liked_channel_ids(session, limit=DEFAULT_MAX_SEEDS)
        never = [
            channel_id for channel_id in liked if stored_featured(session, channel_id) is None
        ][:max_fetches]
    refresh(sessions, gateway, never, now=now)
    with sessions() as session:
        return suggested_channels(session, limit=limit)


def _subscribed_ids(session: Session, channel_ids: list[str]) -> set[str]:
    if not channel_ids:
        return set()
    return set(
        session.execute(
            text("SELECT channel_id FROM channel_prefs WHERE channel_id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": channel_ids},
        ).scalars()
    )


# Candidate source

DEFAULT_SOURCE_CHANNELS = 10
DEFAULT_UPLOADS_PER_CHANNEL = 3


class ChannelGraphSource:
    """The newest uploads of suggested channels (featured by channels I like).

    Refreshes the stale featured channels of up to `max_seeds` liked channels, then
    takes up to `per_channel` uploads from each of the top `max_channels` suggestions,
    attributed to the liked channel that features it first (`source_detail` = that
    channel's id). Rated videos are never candidates. A channel that can't be fetched
    is skipped; the source fails only if every Gateway call failed.
    """

    name = CHANNEL_GRAPH

    def __init__(
        self,
        sessions: sessionmaker[Session],
        gateway: Gateway,
        *,
        max_seeds: int = DEFAULT_MAX_SEEDS,
        max_channels: int = DEFAULT_SOURCE_CHANNELS,
        per_channel: int = DEFAULT_UPLOADS_PER_CHANNEL,
        max_age: timedelta = FEATURED_MAX_AGE,
        now: datetime | None = None,
    ) -> None:
        self._sessions = sessions
        self._gateway = gateway
        self._max_seeds = max_seeds
        self._max_channels = max_channels
        self._per_channel = per_channel
        self._max_age = max_age
        self._now = now

    def fetch(self) -> list[FoundVideo]:
        with self._sessions() as session:
            liked = liked_channel_ids(session, limit=self._max_seeds)
        report = refresh(self._sessions, self._gateway, liked, max_age=self._max_age, now=self._now)
        with self._sessions() as session:
            suggestions = suggested_channels(session, limit=self._max_channels)
            rated = set(session.execute(text("SELECT video_id FROM ratings")).scalars())
        errors = list(report.failed.values())
        attempts = len(report.refreshed) + len(report.failed)
        found: list[FoundVideo] = []
        for suggestion in suggestions:
            attempts += 1
            try:
                uploads = self._gateway.get_channel_uploads(
                    suggestion.channel_id, limit=self._per_channel
                )
            except GatewayError as error:
                logger.warning("Could not fetch uploads of %s: %s", suggestion.channel_id, error)
                errors.append(error)
                continue
            found += [
                FoundVideo(
                    video_id=video.id,
                    title=video.title,
                    channel_id=uploads.channel.id,
                    channel_title=uploads.channel.title or suggestion.title,
                    source_detail=suggestion.featured_by[0].channel_id,
                    channel_handle=uploads.channel.handle or suggestion.handle,
                    duration_seconds=video.duration_seconds,
                    view_count=video.view_count,
                    thumbnail_url=video.thumbnail_url,
                    live_status=video.live_status,
                )
                for video in uploads.videos
                if video.id not in rated
            ]
        if errors and len(errors) == attempts:
            raise errors[-1]
        return found
