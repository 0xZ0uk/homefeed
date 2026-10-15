"""Stored video metadata: the `videos` table and the channels it refers to.

The watch page fetches full metadata through the Gateway and keeps it here, so other
features (history, ratings, the feed) see the richest copy, and a page can still show
the video when YouTube can't be reached.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_core.gateway import Video
from homefeed_core.gateway.events import format_timestamp


@dataclass(frozen=True)
class StoredVideo:
    id: str
    title: str
    channel_id: str
    channel_title: str
    channel_handle: str | None
    channel_thumbnail_url: str | None  # the channel's picture, once the channel was looked up
    description: str | None
    duration_seconds: int | None
    published_at: str | None  # ISO 8601 UTC
    thumbnail_url: str | None
    live_status: str | None


def store_video(session: Session, video: Video) -> None:
    """Insert or update `video` and its channel, keeping fields the Gateway lacks."""
    session.execute(
        text(
            """
            INSERT INTO channels (id, title, handle) VALUES (:id, :title, :handle)
            ON CONFLICT (id) DO UPDATE SET
                title = coalesce(nullif(excluded.title, ''), channels.title),
                handle = coalesce(excluded.handle, channels.handle),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """
        ),
        {"id": video.channel_id, "title": video.channel_title, "handle": video.channel_handle},
    )
    session.execute(
        text(
            """
            INSERT INTO videos (id, channel_id, title, description, duration_seconds,
                                published_at, thumbnail_url, live_status, is_short, view_count)
            VALUES (:id, :channel_id, :title, :description, :duration_seconds,
                    :published_at, :thumbnail_url, :live_status, :is_short, :view_count)
            ON CONFLICT (id) DO UPDATE SET
                title = excluded.title,
                description = coalesce(excluded.description, videos.description),
                duration_seconds = coalesce(excluded.duration_seconds, videos.duration_seconds),
                published_at = coalesce(excluded.published_at, videos.published_at),
                thumbnail_url = coalesce(excluded.thumbnail_url, videos.thumbnail_url),
                live_status = excluded.live_status,
                is_short = excluded.is_short,
                view_count = coalesce(excluded.view_count, videos.view_count),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """
        ),
        {
            "id": video.id,
            "channel_id": video.channel_id,
            "title": video.title,
            "description": video.description,
            "duration_seconds": video.duration_seconds,
            "published_at": format_timestamp(video.published_at) if video.published_at else None,
            "thumbnail_url": video.thumbnail_url,
            "live_status": video.live_status,
            "is_short": int(video.is_short),
            "view_count": video.view_count,
        },
    )


def get_stored_video(session: Session, video_id: str) -> StoredVideo | None:
    row = session.execute(
        text(
            """
            SELECT v.id, v.title, v.channel_id, c.title, c.handle, c.thumbnail_url,
                   v.description, v.duration_seconds, v.published_at, v.thumbnail_url,
                   v.live_status
            FROM videos AS v JOIN channels AS c ON c.id = v.channel_id
            WHERE v.id = :id
            """
        ),
        {"id": video_id},
    ).one_or_none()
    return None if row is None else StoredVideo(*row)
