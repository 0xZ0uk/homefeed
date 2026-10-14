"""Hand curation: channel subscriptions and per-channel preferences (prior, pin, mute),
keyword mutes and tag subscriptions.

A channel is subscribed while it has a row in `channel_prefs`. Subscribing resolves a
pasted URL through the Gateway and upserts the channel into `channels`; unsubscribing
removes the preferences but keeps the channel (its videos and ratings still refer to it).

A keyword mute drops every video whose title or description contains the keyword (see
`ranker.KeywordMutes` for the matching). Keywords are unique ignoring case.

A tag subscription (`tag_subscriptions`, at most one per tag) gives the tag a slider
weight in [-1, 1]: the ranker adds `weight * confidence` to every video carrying the tag
(see `ranker.tag_boosts`). Subscribing (`subscribe_tag`) starts at `SUBSCRIBE_WEIGHT`.
Muting (`mute_tag`) is the same row with a negative weight (`MUTE_WEIGHT`), so the tag's
videos rank lower and the breakdown shows the negative term; `unmute_tag` deletes it. A
muted tag at weight -1 can also set `hide`, which makes the ranker drop every video
carrying the tag, like a keyword mute. `hide` is cleared by any change of the weight to
another value, so a raised weight never keeps hiding. Deleting the tag deletes its
subscription (ON DELETE CASCADE); merging tags moves it (`relink_tag_subscription`).

Tag subscriptions replaced topics (plain-language descriptions matched by embedding); see
migration 0025 for what carried over.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, get_args

from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_core.gateway import Channel, Gateway, ResolvedChannel
from homefeed_core.gateway.events import format_timestamp

if TYPE_CHECKING:
    # Imported for types only: tags.merge_tags calls back into this module.
    from homefeed_core.tags import Tag

Prior = Literal["love", "like", "neutral", "skeptical"]

PRIORS: tuple[Prior, ...] = get_args(Prior)
DEFAULT_PRIOR: Prior = "neutral"

# The channel score's starting point before any ratings (PLAN.md section 7).
PRIOR_VALUES: dict[Prior, float] = {"love": 0.8, "like": 0.4, "neutral": 0.0, "skeptical": -0.4}


# Longest keyword mute, in characters.
KEYWORD_MAX_LENGTH = 100

# The weight of a tag subscription made by subscribing.
SUBSCRIBE_WEIGHT = 0.5
# The weight of a tag subscription made by muting, and the one an existing subscription gets.
MUTE_WEIGHT = -0.5
# The only weight at which a muted tag can hide its videos from the feed.
HIDE_WEIGHT = -1.0


class NotAChannelUrlError(ValueError):
    """The URL is a valid YouTube link, but to a video or playlist rather than a channel."""


class DuplicateKeywordMuteError(ValueError):
    """Another keyword mute already has this keyword (ignoring case)."""


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

    Returns the subscription and whether it is new. Subscribing clears any hide
    (`channel_hides`) of the channel. Subscribing again is a no-op apart
    from refreshing the channel's metadata; existing preferences are kept. Raises
    `NotAChannelUrlError` for video or playlist links, and the Gateway's errors
    (`UnsupportedUrlError`, `UnavailableError`, ...) as they come.
    """
    resolved = gateway.resolve_url(url)
    if not isinstance(resolved, ResolvedChannel):
        raise NotAChannelUrlError(f"Not a channel URL: {url!r}")
    channel = resolved.channel
    upsert_channel(session, channel)
    session.execute(text("DELETE FROM channel_hides WHERE channel_id = :id"), {"id": channel.id})
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


@dataclass(frozen=True)
class KeywordMute:
    id: int
    keyword: str
    created_at: str  # ISO 8601 UTC


def normalize_keyword(keyword: str) -> str:
    """Trim and collapse inner whitespace. Raises `ValueError` if nothing is left or the
    result is longer than `KEYWORD_MAX_LENGTH`."""
    normalized = " ".join(keyword.split())
    if not normalized:
        raise ValueError("Keyword is empty")
    if len(normalized) > KEYWORD_MAX_LENGTH:
        raise ValueError(f"Keyword is longer than {KEYWORD_MAX_LENGTH} characters")
    return normalized


def list_keyword_mutes(session: Session) -> list[KeywordMute]:
    """All keyword mutes, alphabetically."""
    rows = session.execute(
        text("SELECT id, keyword, created_at FROM keyword_mutes ORDER BY keyword, id")
    )
    return [KeywordMute(*row) for row in rows]


def muted_keywords(session: Session) -> list[str]:
    """Just the keywords, for the ranker."""
    return [mute.keyword for mute in list_keyword_mutes(session)]


def add_keyword_mute(session: Session, keyword: str) -> tuple[KeywordMute, bool]:
    """Mute `keyword` (normalized with `normalize_keyword`).

    Returns the mute and whether it is new; muting a keyword again (in any case) returns
    the existing one unchanged.
    """
    keyword = normalize_keyword(keyword)
    row = session.execute(
        text(
            "INSERT INTO keyword_mutes (keyword) VALUES (:keyword) "
            "ON CONFLICT (keyword) DO NOTHING RETURNING id, keyword, created_at"
        ),
        {"keyword": keyword},
    ).one_or_none()
    if row is not None:
        return KeywordMute(*row), True
    existing = session.execute(
        text("SELECT id, keyword, created_at FROM keyword_mutes WHERE keyword = :keyword"),
        {"keyword": keyword},
    ).one()
    return KeywordMute(*existing), False


def update_keyword_mute(session: Session, mute_id: int, keyword: str) -> KeywordMute | None:
    """Change a mute's keyword. Returns `None` if there is no such mute; raises
    `DuplicateKeywordMuteError` if another mute has the keyword."""
    keyword = normalize_keyword(keyword)
    taken = session.execute(
        text("SELECT 1 FROM keyword_mutes WHERE keyword = :keyword AND id != :id"),
        {"id": mute_id, "keyword": keyword},
    ).first()
    if taken is not None:
        raise DuplicateKeywordMuteError(f"{keyword!r} is already muted")
    row = session.execute(
        text(
            "UPDATE keyword_mutes SET keyword = :keyword WHERE id = :id "
            "RETURNING id, keyword, created_at"
        ),
        {"id": mute_id, "keyword": keyword},
    ).one_or_none()
    return None if row is None else KeywordMute(*row)


def delete_keyword_mute(session: Session, mute_id: int) -> bool:
    """Unmute. Returns whether the mute existed."""
    deleted = session.execute(
        text("DELETE FROM keyword_mutes WHERE id = :id RETURNING id"), {"id": mute_id}
    ).first()
    return deleted is not None


@dataclass(frozen=True)
class TagSubscription:
    """A subscribed or muted tag: videos carrying it get `weight * confidence` added to
    their score (see `ranker.tag_boosts`)."""

    tag_id: int
    slug: str
    label: str
    weight: float  # the slider, in [-1, 1]: positive subscribed, negative muted
    # Drop the tag's videos from the feed instead of only ranking them down. Only possible
    # at weight -1; changing the weight to anything else clears it.
    hide: bool
    created_at: str  # ISO 8601 UTC
    updated_at: str  # ISO 8601 UTC

    @property
    def muted(self) -> bool:
        return self.weight < 0


def _check_weight(weight: float) -> float:
    if not -1.0 <= weight <= 1.0:
        raise ValueError("Tag weight must be between -1 and 1")
    return float(weight)


_SUBSCRIPTION_SELECT = """
    SELECT s.tag_id, t.slug, t.label, s.weight, s.hide, s.created_at, s.updated_at
    FROM tag_subscriptions AS s JOIN tags AS t ON t.id = s.tag_id
"""


def list_tag_subscriptions(session: Session) -> list[TagSubscription]:
    """Every subscribed and muted tag, by label."""
    rows = session.execute(text(f"{_SUBSCRIPTION_SELECT} ORDER BY t.label COLLATE NOCASE, t.id"))
    return [_subscription(row) for row in rows]


def tag_subscription(session: Session, tag_id: int) -> TagSubscription | None:
    """The tag's subscription (or mute), or None if it has neither."""
    row = session.execute(
        text(f"{_SUBSCRIPTION_SELECT} WHERE s.tag_id = :tag_id"), {"tag_id": tag_id}
    ).one_or_none()
    return None if row is None else _subscription(row)


def subscribe_tag(
    session: Session,
    tag: "Tag",
    *,
    weight: float = SUBSCRIBE_WEIGHT,
    now: datetime | None = None,
) -> tuple[TagSubscription, bool]:
    """Subscribe to `tag` with `weight`. Returns the subscription and whether it was
    created; an existing one (subscribed or muted) is left as it is."""
    weight = _check_weight(weight)
    timestamp = format_timestamp(now or datetime.now(UTC))
    created = session.execute(
        text(
            """
            INSERT INTO tag_subscriptions (tag_id, weight, created_at, updated_at)
            VALUES (:tag_id, :weight, :now, :now)
            ON CONFLICT (tag_id) DO NOTHING
            RETURNING tag_id
            """
        ),
        {"tag_id": tag.id, "weight": weight, "now": timestamp},
    ).first()
    subscription = tag_subscription(session, tag.id)
    assert subscription is not None
    return subscription, created is not None


def unsubscribe_tag(session: Session, tag_id: int) -> bool:
    """Delete the tag's subscription (or mute). Returns whether it had one."""
    deleted = session.execute(
        text("DELETE FROM tag_subscriptions WHERE tag_id = :tag_id RETURNING tag_id"),
        {"tag_id": tag_id},
    ).first()
    return deleted is not None


def mute_tag(session: Session, tag: "Tag", *, now: datetime | None = None) -> TagSubscription:
    """Mute `tag`: a negative weight, so its videos rank lower. Without a subscription one
    is made with weight `MUTE_WEIGHT`; a subscription (weight >= 0) is flipped to
    `MUTE_WEIGHT`; a tag that is already muted is left as it is."""
    subscription, created = subscribe_tag(session, tag, weight=MUTE_WEIGHT, now=now)
    if created or subscription.muted:
        return subscription
    updated = update_tag_subscription(session, tag.id, weight=MUTE_WEIGHT, now=now)
    assert updated is not None
    return updated


def unmute_tag(session: Session, tag_id: int) -> bool:
    """Delete the tag's subscription if it is muted (negative weight). Returns whether it
    was."""
    deleted = session.execute(
        text(
            "DELETE FROM tag_subscriptions WHERE tag_id = :tag_id AND weight < 0 RETURNING tag_id"
        ),
        {"tag_id": tag_id},
    ).first()
    return deleted is not None


def update_tag_subscription(
    session: Session,
    tag_id: int,
    *,
    weight: float | None = None,
    hide: bool | None = None,
    now: datetime | None = None,
) -> TagSubscription | None:
    """Change the weight and/or `hide` (`None` leaves one as is). Returns `None` if the tag
    has no subscription.

    `hide` can only be turned on at weight -1 (after this update), else `ValueError`.
    Setting the weight to anything but -1 turns it off, unless the same call sets `hide`.
    Raises `ValueError` for a weight outside [-1, 1].
    """
    current = tag_subscription(session, tag_id)
    if current is None:
        return None
    new_weight = current.weight if weight is None else _check_weight(weight)
    new_hide = current.hide if hide is None else hide
    if new_hide and new_weight != HIDE_WEIGHT:
        if hide:
            raise ValueError("Only a tag with weight -1 can hide its videos")
        new_hide = False
    if (new_weight, new_hide) != (current.weight, current.hide):
        session.execute(
            text(
                """
                UPDATE tag_subscriptions SET weight = :weight, hide = :hide, updated_at = :now
                WHERE tag_id = :tag_id
                """
            ),
            {
                "tag_id": tag_id,
                "weight": new_weight,
                "hide": int(new_hide),
                "now": format_timestamp(now or datetime.now(UTC)),
            },
        )
    return tag_subscription(session, tag_id)


def relink_tag_subscription(session: Session, source_tag_id: int, target_tag_id: int) -> None:
    """For merging tag `source_tag_id` into `target_tag_id`, before the source is deleted:
    the source's subscription follows to the target. If the target has one too, the
    source's is deleted instead (the target's weight stands). Does nothing if the source
    has none."""
    if tag_subscription(session, target_tag_id) is not None:
        unsubscribe_tag(session, source_tag_id)
        return
    session.execute(
        text("UPDATE tag_subscriptions SET tag_id = :target WHERE tag_id = :source"),
        {"source": source_tag_id, "target": target_tag_id},
    )


def _subscription(row: Sequence[Any]) -> TagSubscription:
    tag_id, slug, label, weight, hide, created_at, updated_at = row
    return TagSubscription(
        tag_id=tag_id,
        slug=slug,
        label=label,
        weight=weight,
        hide=bool(hide),
        created_at=created_at,
        updated_at=updated_at,
    )


def upsert_channel(session: Session, channel: Channel) -> None:
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
