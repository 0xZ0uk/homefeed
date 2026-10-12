"""Hand curation: channel subscriptions and per-channel preferences (prior, pin, mute).

A channel is subscribed while it has a row in `channel_prefs`. Subscribing resolves a
pasted URL through the Gateway and upserts the channel into `channels`; unsubscribing
removes the preferences but keeps the channel (its videos and ratings still refer to it).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, get_args

from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_core.gateway import Channel, Gateway, ResolvedChannel

Prior = Literal["love", "like", "neutral", "skeptical"]

PRIORS: tuple[Prior, ...] = get_args(Prior)
DEFAULT_PRIOR: Prior = "neutral"

# The channel score's starting point before any ratings (PLAN.md section 7).
PRIOR_VALUES: dict[Prior, float] = {"love": 0.8, "like": 0.4, "neutral": 0.0, "skeptical": -0.4}


class NotAChannelUrlError(ValueError):
    """The URL is a valid YouTube link, but to a video or playlist rather than a channel."""


@dataclass(frozen=True)
class SubscribedChannel:
    channel_id: str
    title: str
    handle: str | None
    url: str | None
    thumbnail_url: str | None
    prior: Prior
    pinned: bool
    muted: bool
    subscribed_at: str  # ISO 8601 UTC
    updated_at: str  # ISO 8601 UTC; when the preferences last changed


_SELECT = """
    SELECT c.id, c.title, c.handle, c.url, c.thumbnail_url,
           p.prior, p.pinned, p.muted, p.subscribed_at, p.updated_at
    FROM channel_prefs AS p JOIN channels AS c ON c.id = p.channel_id
"""


def subscribe(session: Session, gateway: Gateway, url: str) -> tuple[SubscribedChannel, bool]:
    """Subscribe to the channel at `url` (any channel URL form, or a bare @handle).

    Returns the subscription and whether it is new. Subscribing again is a no-op apart
    from refreshing the channel's metadata; existing preferences are kept. Raises
    `NotAChannelUrlError` for video or playlist links, and the Gateway's errors
    (`UnsupportedUrlError`, `UnavailableError`, ...) as they come.
    """
    resolved = gateway.resolve_url(url)
    if not isinstance(resolved, ResolvedChannel):
        raise NotAChannelUrlError(f"Not a channel URL: {url!r}")
    channel = resolved.channel
    _upsert_channel(session, channel)
    inserted = session.execute(
        text(
            "INSERT INTO channel_prefs (channel_id) VALUES (:id) "
            "ON CONFLICT (channel_id) DO NOTHING RETURNING channel_id"
        ),
        {"id": channel.id},
    ).first()
    subscription = get_channel(session, channel.id)
    assert subscription is not None
    return subscription, inserted is not None


def list_channels(session: Session) -> list[SubscribedChannel]:
    """All subscriptions, pinned first, then by title."""
    rows = session.execute(text(f"{_SELECT} ORDER BY p.pinned DESC, c.title COLLATE NOCASE, c.id"))
    return [_from_row(row) for row in rows]


def get_channel(session: Session, channel_id: str) -> SubscribedChannel | None:
    row = session.execute(
        text(f"{_SELECT} WHERE p.channel_id = :id"), {"id": channel_id}
    ).one_or_none()
    return None if row is None else _from_row(row)


def subscribed_channel_ids(session: Session) -> list[str]:
    """Ids of every subscribed channel, muted ones included."""
    return list(session.execute(text("SELECT channel_id FROM channel_prefs")).scalars())


def update_channel(
    session: Session,
    channel_id: str,
    *,
    prior: Prior | None = None,
    pinned: bool | None = None,
    muted: bool | None = None,
) -> SubscribedChannel | None:
    """Change the given preferences (`None` leaves one as is). Returns `None` if the
    channel isn't subscribed."""
    if prior is not None and prior not in PRIORS:
        raise ValueError(f"Unknown prior {prior!r}")
    changes = {
        name: value
        for name, value in (("prior", prior), ("pinned", pinned), ("muted", muted))
        if value is not None
    }
    if changes:
        assignments = ", ".join(f"{name} = :{name}" for name in changes)
        session.execute(
            text(
                f"UPDATE channel_prefs SET {assignments}, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE channel_id = :id"
            ),
            {"id": channel_id, **changes},
        )
    return get_channel(session, channel_id)


def unsubscribe(session: Session, channel_id: str) -> bool:
    """Drop the subscription and its preferences. Returns whether one existed."""
    deleted = session.execute(
        text("DELETE FROM channel_prefs WHERE channel_id = :id RETURNING channel_id"),
        {"id": channel_id},
    ).first()
    return deleted is not None


def _upsert_channel(session: Session, channel: Channel) -> None:
    session.execute(
        text(
            """
            INSERT INTO channels (id, title, handle, url, thumbnail_url)
            VALUES (:id, :title, :handle, :url, :thumbnail_url)
            ON CONFLICT (id) DO UPDATE SET
                title = excluded.title,
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


def _from_row(row: Sequence[Any]) -> SubscribedChannel:
    (channel_id, title, handle, url, thumbnail_url, prior, pinned, muted, subscribed, updated) = row
    return SubscribedChannel(
        channel_id=channel_id,
        title=title,
        handle=handle,
        url=url,
        thumbnail_url=thumbnail_url,
        prior=prior,
        pinned=bool(pinned),
        muted=bool(muted),
        subscribed_at=subscribed,
        updated_at=updated,
    )
