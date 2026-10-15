"""Hidden channels: channels I don't want to see suggested on Discover.

The app words the two kinds as "Not now" and "Hide channel".

A `dismissed` channel ("Not now") is only left out of the suggestions; its videos can
still reach the feed. A `blocked` channel ("Hide channel") is also treated like a muted
channel by the ranker (none of its videos reach the feed or the Discovery carousel), and
it is no longer a seed of the channel graph or a source of tag discovery results. Hiding
again changes the kind and time; subscribing to a channel clears its hide
(`curation.subscribe`). Ending a channel trial records a `dismissed` hide too (see
homefeed_core.trials).
"""

from dataclasses import dataclass
from typing import Literal, get_args

from sqlalchemy import text
from sqlalchemy.orm import Session

HideKind = Literal["dismissed", "blocked"]
HIDE_KINDS: tuple[str, ...] = get_args(HideKind)


@dataclass(frozen=True)
class ChannelHide:
    channel_id: str
    title: str
    handle: str | None
    thumbnail_url: str | None
    kind: HideKind
    hidden_at: str  # ISO 8601 UTC


_SELECT = """
    SELECT h.channel_id, c.title, c.handle, c.thumbnail_url, h.kind, h.hidden_at
    FROM channel_hides AS h JOIN channels AS c ON c.id = h.channel_id
"""


def hide(session: Session, channel_id: str, kind: HideKind) -> ChannelHide | None:
    """Hide a channel, or change how it is hidden (blocked or dismissed, whichever was
    asked last) and when. Returns `None` if the channel isn't in `channels`."""
    if kind not in HIDE_KINDS:
        raise ValueError(f"Unknown hide kind {kind!r}")
    known = session.execute(
        text("SELECT 1 FROM channels WHERE id = :id"), {"id": channel_id}
    ).first()
    if known is None:
        return None
    session.execute(
        text(
            """
            INSERT INTO channel_hides (channel_id, kind) VALUES (:id, :kind)
            ON CONFLICT (channel_id) DO UPDATE SET
                kind = excluded.kind,
                hidden_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """
        ),
        {"id": channel_id, "kind": kind},
    )
    return get_hide(session, channel_id)


def unhide(session: Session, channel_id: str) -> bool:
    """Show a channel again. Returns whether it was hidden."""
    deleted = session.execute(
        text("DELETE FROM channel_hides WHERE channel_id = :id RETURNING channel_id"),
        {"id": channel_id},
    ).first()
    return deleted is not None


def get_hide(session: Session, channel_id: str) -> ChannelHide | None:
    row = session.execute(
        text(f"{_SELECT} WHERE h.channel_id = :id"), {"id": channel_id}
    ).one_or_none()
    return None if row is None else ChannelHide(*row)


def list_hides(session: Session) -> list[ChannelHide]:
    """All hidden channels, most recently hidden first."""
    rows = session.execute(text(f"{_SELECT} ORDER BY h.hidden_at DESC, h.channel_id"))
    return [ChannelHide(*row) for row in rows]


def blocked_channel_ids(session: Session) -> set[str]:
    return set(
        session.execute(
            text("SELECT channel_id FROM channel_hides WHERE kind = 'blocked'")
        ).scalars()
    )
