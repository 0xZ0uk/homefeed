"""Hand curation: channel subscriptions and per-channel preferences (prior, pin, mute),
keyword mutes and topics.

A channel is subscribed while it has a row in `channel_prefs`. Subscribing resolves a
pasted URL through the Gateway and upserts the channel into `channels`; unsubscribing
removes the preferences but keeps the channel (its videos and ratings still refer to it).

A keyword mute drops every video whose title or description contains the keyword (see
`ranker.KeywordMutes` for the matching). Keywords are unique ignoring case.

A topic boosts (or, with a negative weight, suppresses) videos similar to its
plain-language description: the ranker adds `weight * max(0, cos_sim - 0.3) / 0.7`
(see `ranker.topic_boost`). With decay on, the weight halves every
`TOPIC_HALF_LIFE_DAYS` since the topic was last reaffirmed; setting the weight or turning
decay on counts as reaffirming. Topic names are unique ignoring case; they key the
topic's term in feed items' score breakdowns.

Topic descriptions are embedded when they are saved, with the provider the caller passes
(the API's is loaded on its first use, so it only loads the model once a topic is saved).
The worker re-embeds topics after an `EMBEDDING_MODEL` change with
`refresh_topic_embeddings`, so topic and video vectors come from the same model.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, get_args

from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_core.embeddings import (
    Embedding,
    EmbeddingProvider,
    deserialize_embedding,
    serialize_embedding,
)
from homefeed_core.gateway import Channel, Gateway, ResolvedChannel
from homefeed_core.gateway.events import format_timestamp

Prior = Literal["love", "like", "neutral", "skeptical"]

PRIORS: tuple[Prior, ...] = get_args(Prior)
DEFAULT_PRIOR: Prior = "neutral"

# The channel score's starting point before any ratings (PLAN.md section 7).
PRIOR_VALUES: dict[Prior, float] = {"love": 0.8, "like": 0.4, "neutral": 0.0, "skeptical": -0.4}


# Longest keyword mute, in characters.
KEYWORD_MAX_LENGTH = 100

# Longest topic name and description, in characters.
TOPIC_NAME_MAX_LENGTH = 60
TOPIC_DESCRIPTION_MAX_LENGTH = 500
# With decay on, a topic's weight halves every this many days unless reaffirmed.
TOPIC_HALF_LIFE_DAYS = 30


class NotAChannelUrlError(ValueError):
    """The URL is a valid YouTube link, but to a video or playlist rather than a channel."""


class DuplicateKeywordMuteError(ValueError):
    """Another keyword mute already has this keyword (ignoring case)."""


class DuplicateTopicError(ValueError):
    """Another topic already has this name (ignoring case)."""


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
class Topic:
    id: int
    name: str
    description: str
    weight: float  # the slider, in [-1, 1]
    decay: bool
    # The weight in effect now: `weight`, halved every TOPIC_HALF_LIFE_DAYS since
    # `reaffirmed_at` when `decay` is on.
    effective_weight: float
    reaffirmed_at: str  # ISO 8601 UTC
    created_at: str  # ISO 8601 UTC
    updated_at: str  # ISO 8601 UTC


@dataclass(frozen=True)
class TopicVector:
    """What the ranker needs of a topic: its name, effective weight and embedding."""

    name: str
    weight: float
    embedding: Embedding


def decayed_weight(weight: float, *, decay: bool, reaffirmed_at: datetime, now: datetime) -> float:
    """`weight * 0.5 ** (days since reaffirmed_at / TOPIC_HALF_LIFE_DAYS)` with decay on,
    else `weight`."""
    if not decay:
        return weight
    age_days = max(0.0, (now - reaffirmed_at).total_seconds() / 86400)
    return weight * 0.5 ** (age_days / TOPIC_HALF_LIFE_DAYS)


def normalize_topic_name(name: str) -> str:
    """Trim and collapse inner whitespace. Raises `ValueError` if nothing is left or the
    result is longer than `TOPIC_NAME_MAX_LENGTH`."""
    normalized = " ".join(name.split())
    if not normalized:
        raise ValueError("Topic name is empty")
    if len(normalized) > TOPIC_NAME_MAX_LENGTH:
        raise ValueError(f"Topic name is longer than {TOPIC_NAME_MAX_LENGTH} characters")
    return normalized


def normalize_topic_description(description: str) -> str:
    """Trim. Raises `ValueError` if nothing is left or the result is longer than
    `TOPIC_DESCRIPTION_MAX_LENGTH`."""
    normalized = description.strip()
    if not normalized:
        raise ValueError("Topic description is empty")
    if len(normalized) > TOPIC_DESCRIPTION_MAX_LENGTH:
        raise ValueError(
            f"Topic description is longer than {TOPIC_DESCRIPTION_MAX_LENGTH} characters"
        )
    return normalized


def _check_weight(weight: float) -> float:
    if not -1.0 <= weight <= 1.0:
        raise ValueError("Topic weight must be between -1 and 1")
    return float(weight)


_TOPIC_COLUMNS = "id, name, description, weight, decay, reaffirmed_at, created_at, updated_at"


def list_topics(session: Session, *, now: datetime | None = None) -> list[Topic]:
    """All topics, alphabetically, with their weights as of `now` (default: now)."""
    now = now or datetime.now(UTC)
    rows = session.execute(
        text(f"SELECT {_TOPIC_COLUMNS} FROM topics ORDER BY name COLLATE NOCASE, id")
    )
    return [_topic(row, now) for row in rows]


def get_topic(session: Session, topic_id: int, *, now: datetime | None = None) -> Topic | None:
    row = session.execute(
        text(f"SELECT {_TOPIC_COLUMNS} FROM topics WHERE id = :id"), {"id": topic_id}
    ).one_or_none()
    return None if row is None else _topic(row, now or datetime.now(UTC))


def add_topic(
    session: Session,
    embedder: EmbeddingProvider,
    *,
    name: str,
    description: str,
    weight: float,
    decay: bool = False,
    now: datetime | None = None,
) -> Topic:
    """Create a topic, embedding its description with `embedder`.

    Raises `DuplicateTopicError` if another topic has the name (ignoring case) and
    `ValueError` for a blank or too long name or description or a weight outside [-1, 1].
    """
    now = now or datetime.now(UTC)
    name = normalize_topic_name(name)
    description = normalize_topic_description(description)
    weight = _check_weight(weight)
    _check_name_free(session, name)
    [embedding] = embedder.embed([description])
    topic_id = session.execute(
        text(
            """
            INSERT INTO topics (name, description, embedding, embedding_model, weight, decay,
                                reaffirmed_at, created_at, updated_at)
            VALUES (:name, :description, :embedding, :model, :weight, :decay,
                    :now, :now, :now)
            RETURNING id
            """
        ),
        {
            "name": name,
            "description": description,
            "embedding": serialize_embedding(embedding),
            "model": embedder.model,
            "weight": weight,
            "decay": int(decay),
            "now": format_timestamp(now),
        },
    ).scalar_one()
    topic = get_topic(session, topic_id, now=now)
    assert topic is not None
    return topic


def update_topic(
    session: Session,
    embedder: EmbeddingProvider,
    topic_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    weight: float | None = None,
    decay: bool | None = None,
    now: datetime | None = None,
) -> Topic | None:
    """Change the given fields (`None` leaves one as is). Returns `None` if there is no
    such topic.

    A changed description is embedded again with `embedder`. Setting the weight, or
    turning decay on, reaffirms the topic (restarts its decay). Raises like `add_topic`.
    """
    now = now or datetime.now(UTC)
    row = session.execute(
        text("SELECT description, decay FROM topics WHERE id = :id"), {"id": topic_id}
    ).one_or_none()
    if row is None:
        return None
    old_description, old_decay = row
    changes: dict[str, object] = {}
    if name is not None:
        name = normalize_topic_name(name)
        _check_name_free(session, name, other_than=topic_id)
        changes["name"] = name
    if description is not None:
        description = normalize_topic_description(description)
        if description != old_description:
            [embedding] = embedder.embed([description])
            changes["description"] = description
            changes["embedding"] = serialize_embedding(embedding)
            changes["embedding_model"] = embedder.model
    if weight is not None:
        changes["weight"] = _check_weight(weight)
    if decay is not None:
        changes["decay"] = int(decay)
    if weight is not None or (decay and not old_decay):
        changes["reaffirmed_at"] = format_timestamp(now)
    if changes:
        assignments = ", ".join(f"{column} = :{column}" for column in changes)
        session.execute(
            text(f"UPDATE topics SET {assignments}, updated_at = :now WHERE id = :id"),
            {"id": topic_id, "now": format_timestamp(now), **changes},
        )
    return get_topic(session, topic_id, now=now)


def reaffirm_topic(session: Session, topic_id: int, *, now: datetime | None = None) -> Topic | None:
    """Restart the topic's decay: its full weight applies again. Returns `None` if there
    is no such topic."""
    now = now or datetime.now(UTC)
    session.execute(
        text("UPDATE topics SET reaffirmed_at = :now, updated_at = :now WHERE id = :id"),
        {"id": topic_id, "now": format_timestamp(now)},
    )
    return get_topic(session, topic_id, now=now)


def delete_topic(session: Session, topic_id: int) -> bool:
    """Remove a topic. Returns whether it existed."""
    deleted = session.execute(
        text("DELETE FROM topics WHERE id = :id RETURNING id"), {"id": topic_id}
    ).first()
    return deleted is not None


def topic_vectors(session: Session, *, now: datetime | None = None) -> list[TopicVector]:
    """Every topic's name, effective weight (as of `now`) and embedding, for the ranker."""
    now = now or datetime.now(UTC)
    rows = session.execute(
        text("SELECT name, weight, decay, reaffirmed_at, embedding FROM topics ORDER BY id")
    )
    return [
        TopicVector(
            name=name,
            weight=decayed_weight(
                weight, decay=bool(decay), reaffirmed_at=_parse_timestamp(reaffirmed), now=now
            ),
            embedding=deserialize_embedding(blob),
        )
        for name, weight, decay, reaffirmed, blob in rows
    ]


def refresh_topic_embeddings(session: Session, embedder: EmbeddingProvider) -> list[int]:
    """Re-embed the descriptions of topics embedded by another model than `embedder`'s
    (after an `EMBEDDING_MODEL` change). Returns the ids of the topics re-embedded."""
    rows = session.execute(
        text("SELECT id, description FROM topics WHERE embedding_model != :model ORDER BY id"),
        {"model": embedder.model},
    ).all()
    if not rows:
        return []
    vectors = embedder.embed([description for _, description in rows])
    session.execute(
        text("UPDATE topics SET embedding = :embedding, embedding_model = :model WHERE id = :id"),
        [
            {"id": topic_id, "embedding": serialize_embedding(vector), "model": embedder.model}
            for (topic_id, _), vector in zip(rows, vectors, strict=True)
        ],
    )
    return [topic_id for topic_id, _ in rows]


def _check_name_free(session: Session, name: str, *, other_than: int | None = None) -> None:
    taken = session.execute(
        text("SELECT 1 FROM topics WHERE name = :name AND id IS NOT :id"),
        {"name": name, "id": other_than},
    ).first()
    if taken is not None:
        raise DuplicateTopicError(f"There is already a topic named {name!r}")


def _topic(row: Sequence[Any], now: datetime) -> Topic:
    topic_id, name, description, weight, decay, reaffirmed_at, created_at, updated_at = row
    return Topic(
        id=topic_id,
        name=name,
        description=description,
        weight=weight,
        decay=bool(decay),
        effective_weight=decayed_weight(
            weight, decay=bool(decay), reaffirmed_at=_parse_timestamp(reaffirmed_at), now=now
        ),
        reaffirmed_at=reaffirmed_at,
        created_at=created_at,
        updated_at=updated_at,
    )


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


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
