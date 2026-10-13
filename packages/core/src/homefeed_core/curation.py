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

A topic can be backed by a tag (`tag_id`, at most one topic per tag): subscribing to a tag
(`subscribe_tag`) creates one with weight `SUBSCRIBE_WEIGHT`, named after the tag's label
(with " (tag)" added if another topic has that name) and match mode 'tag'. `match_mode` says
how the ranker matches videos: 'embedding' (description similarity, the only mode of topics
without a tag), 'tag' (the video carries the tag: `weight * confidence`) or 'both' (the
stronger of the two; see `ranker.topic_boosts`). A tag-backed topic's description is
optional and defaults to the tag's label, which is embedded like any description, so the
mode can be switched at any time. Deleting the tag deletes its topic (ON DELETE CASCADE).

Muting a tag (`mute_tag`) is the same topic with a negative weight (`MUTE_WEIGHT`), so its
videos rank lower and the breakdown shows the negative term; `unmute_tag` deletes it. A
muted tag topic at weight -1 can also set `hide`, which makes the ranker drop every video
carrying the tag, like a keyword mute. `hide` is tied to the stored weight (not the decayed
one): it stays on while the weight is -1, whatever the decay, and is cleared by any change
of the weight to another value, so a raised weight never keeps hiding.

Topic descriptions are embedded when they are saved, with the provider the caller passes
(the API's is loaded on its first use, so it only loads the model once a topic is saved).
The worker re-embeds topics after an `EMBEDDING_MODEL` change with
`refresh_topic_embeddings`, so topic and video vectors come from the same model.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast, get_args

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

# Longest topic name and description, in characters.
TOPIC_NAME_MAX_LENGTH = 60
TOPIC_DESCRIPTION_MAX_LENGTH = 500
# The weight of a topic made by subscribing to a tag.
SUBSCRIBE_WEIGHT = 0.5
# The weight of a topic made by muting a tag, and the one an existing subscription gets.
MUTE_WEIGHT = -0.5
# The only weight at which a tag topic can hide its videos from the feed.
HIDE_WEIGHT = -1.0
MatchMode = Literal["embedding", "tag", "both"]
MATCH_MODES: tuple[MatchMode, ...] = get_args(MatchMode)
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
    match_mode: MatchMode
    # Drop the tag's videos from the feed instead of only ranking them down. Only possible
    # for a tag topic at weight -1; changing the weight to anything else clears it.
    hide: bool
    tag_id: int | None  # the tag this topic is about (and, with it, tag_slug and tag_label)
    tag_slug: str | None
    tag_label: str | None
    # The weight in effect now: `weight`, halved every TOPIC_HALF_LIFE_DAYS since
    # `reaffirmed_at` when `decay` is on.
    effective_weight: float
    reaffirmed_at: str  # ISO 8601 UTC
    created_at: str  # ISO 8601 UTC
    updated_at: str  # ISO 8601 UTC


@dataclass(frozen=True)
class TopicVector:
    """What the ranker needs of a topic: its name, effective weight, embedding and how it
    matches (`tag_id` is None for topics without a tag)."""

    name: str
    weight: float
    embedding: Embedding
    match_mode: MatchMode = "embedding"
    tag_id: int | None = None
    hide: bool = False  # the ranker drops videos carrying `tag_id`


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


def normalize_match_mode(match_mode: str) -> MatchMode:
    if match_mode not in MATCH_MODES:
        raise ValueError(f"Topic match mode must be one of {', '.join(MATCH_MODES)}")
    return cast(MatchMode, match_mode)


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


_TOPIC_SELECT = """
    SELECT p.id, p.name, p.description, p.weight, p.decay, p.reaffirmed_at, p.created_at,
           p.updated_at, p.match_mode, p.tag_id, t.slug, t.label, p.hide
    FROM topics AS p LEFT JOIN tags AS t ON t.id = p.tag_id
"""


def list_topics(session: Session, *, now: datetime | None = None) -> list[Topic]:
    """All topics, alphabetically, with their weights as of `now` (default: now)."""
    now = now or datetime.now(UTC)
    rows = session.execute(text(f"{_TOPIC_SELECT} ORDER BY p.name COLLATE NOCASE, p.id"))
    return [_topic(row, now) for row in rows]


def get_topic(session: Session, topic_id: int, *, now: datetime | None = None) -> Topic | None:
    row = session.execute(text(f"{_TOPIC_SELECT} WHERE p.id = :id"), {"id": topic_id}).one_or_none()
    return None if row is None else _topic(row, now or datetime.now(UTC))


def topic_for_tag(session: Session, tag_id: int, *, now: datetime | None = None) -> Topic | None:
    """The topic backed by the tag, or None if the tag is not subscribed."""
    row = session.execute(
        text(f"{_TOPIC_SELECT} WHERE p.tag_id = :tag_id"), {"tag_id": tag_id}
    ).one_or_none()
    return None if row is None else _topic(row, now or datetime.now(UTC))


def add_topic(
    session: Session,
    embedder: EmbeddingProvider,
    *,
    name: str,
    description: str | None = None,
    weight: float,
    decay: bool = False,
    tag_id: int | None = None,
    match_mode: MatchMode | None = None,
    now: datetime | None = None,
) -> Topic:
    """Create a topic, embedding its description with `embedder`.

    With a `tag_id` the topic is tag-backed: `description` defaults to the tag's label and
    `match_mode` to 'tag'. Without one, `description` is required and the mode is
    'embedding'.

    Raises `DuplicateTopicError` if another topic has the name (ignoring case) or the tag,
    and `ValueError` for a blank or too long name or description, a weight outside [-1, 1],
    an unknown tag or a 'tag' or 'both' mode without a tag.
    """
    now = now or datetime.now(UTC)
    name = normalize_topic_name(name)
    tag = None if tag_id is None else _require_tag(session, tag_id)
    if description is None and tag is not None:
        description = tag.label
    elif description is None:
        raise ValueError("Topic description is empty")
    description = normalize_topic_description(description)
    match_mode = _check_match_mode(match_mode or ("embedding" if tag is None else "tag"), tag)
    weight = _check_weight(weight)
    _check_name_free(session, name)
    if tag is not None:
        _check_tag_free(session, tag.id)
    [embedding] = embedder.embed([description])
    topic_id = session.execute(
        text(
            """
            INSERT INTO topics (name, description, embedding, embedding_model, weight, decay,
                                tag_id, match_mode, reaffirmed_at, created_at, updated_at)
            VALUES (:name, :description, :embedding, :model, :weight, :decay,
                    :tag_id, :match_mode, :now, :now, :now)
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
            "tag_id": None if tag is None else tag.id,
            "match_mode": match_mode,
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
    match_mode: MatchMode | None = None,
    hide: bool | None = None,
    now: datetime | None = None,
) -> Topic | None:
    """Change the given fields (`None` leaves one as is). Returns `None` if there is no
    such topic.

    A changed description is embedded again with `embedder`. Setting the weight, or
    turning decay on, reaffirms the topic (restarts its decay). The tag of a topic cannot
    change. Raises like `add_topic`.

    `hide` can only be turned on for a tag topic whose weight is -1 (after this update),
    else `ValueError`. Setting the weight to anything but -1 turns it off, unless the same
    call sets `hide`.
    """
    now = now or datetime.now(UTC)
    row = session.execute(
        text("SELECT description, decay, tag_id, weight, hide FROM topics WHERE id = :id"),
        {"id": topic_id},
    ).one_or_none()
    if row is None:
        return None
    old_description, old_decay, tag_id, old_weight, old_hide = row
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
    if match_mode is not None:
        tag = None if tag_id is None else _require_tag(session, tag_id)
        changes["match_mode"] = _check_match_mode(match_mode, tag)
    if weight is not None:
        changes["weight"] = _check_weight(weight)
    new_weight = changes.get("weight", old_weight)
    new_hide = bool(old_hide) if hide is None else hide
    if new_hide and new_weight != HIDE_WEIGHT:
        if hide:
            raise ValueError("Only a topic with weight -1 can hide its videos")
        new_hide = False
    if new_hide and tag_id is None:
        raise ValueError("Only a tag topic can hide its videos")
    if new_hide != bool(old_hide):
        changes["hide"] = int(new_hide)
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
        text(
            """
            SELECT name, weight, decay, reaffirmed_at, embedding, match_mode, tag_id, hide
            FROM topics ORDER BY id
            """
        )
    )
    return [
        TopicVector(
            name=name,
            weight=decayed_weight(
                weight, decay=bool(decay), reaffirmed_at=_parse_timestamp(reaffirmed), now=now
            ),
            embedding=deserialize_embedding(blob),
            match_mode=cast(MatchMode, match_mode),
            tag_id=tag_id,
            hide=bool(hide),
        )
        for name, weight, decay, reaffirmed, blob, match_mode, tag_id, hide in rows
    ]


def subscribe_tag(
    session: Session,
    embedder: EmbeddingProvider,
    tag: "Tag",
    *,
    weight: float = SUBSCRIBE_WEIGHT,
    now: datetime | None = None,
) -> tuple[Topic, bool]:
    """Subscribe to `tag`: a tag-backed topic named after its label, matching by tag. Returns
    the topic and whether it was created; an existing subscription is left as it is.

    If another topic already has the tag's label as its name, the name becomes
    "<label> (tag)" (then "(tag 2)", and so on).
    """
    existing = topic_for_tag(session, tag.id, now=now)
    if existing is not None:
        return existing, False
    name = _free_name(session, tag.label)
    topic = add_topic(
        session, embedder, name=name, weight=weight, tag_id=tag.id, match_mode="tag", now=now
    )
    return topic, True


def unsubscribe_tag(session: Session, tag_id: int) -> bool:
    """Delete the tag's topic. Returns whether the tag was subscribed."""
    deleted = session.execute(
        text("DELETE FROM topics WHERE tag_id = :tag_id RETURNING id"), {"tag_id": tag_id}
    ).first()
    return deleted is not None


def mute_tag(
    session: Session,
    embedder: EmbeddingProvider,
    tag: "Tag",
    *,
    now: datetime | None = None,
) -> Topic:
    """Mute `tag`: its topic gets a negative weight, so its videos rank lower. Without a
    topic one is made with weight `MUTE_WEIGHT`; a subscription (weight >= 0) is flipped to
    `MUTE_WEIGHT`; a topic that is already negative is left as it is."""
    topic, created = subscribe_tag(session, embedder, tag, weight=MUTE_WEIGHT, now=now)
    if created or topic.weight < 0:
        return topic
    updated = update_topic(session, embedder, topic.id, weight=MUTE_WEIGHT, now=now)
    assert updated is not None
    return updated


def unmute_tag(session: Session, tag_id: int) -> bool:
    """Delete the tag's topic if it is muted (negative weight). Returns whether it was."""
    deleted = session.execute(
        text("DELETE FROM topics WHERE tag_id = :tag_id AND weight < 0 RETURNING id"),
        {"tag_id": tag_id},
    ).first()
    return deleted is not None


def relink_tag_topic(session: Session, source_tag_id: int, target_tag_id: int) -> None:
    """For merging tag `source_tag_id` into `target_tag_id`, before the source is deleted:
    the source's topic follows to the target. If the target has a topic too, the source's
    is deleted instead (the target's weight stands). Does nothing if the source has none."""
    if topic_for_tag(session, target_tag_id) is not None:
        unsubscribe_tag(session, source_tag_id)
        return
    session.execute(
        text("UPDATE topics SET tag_id = :target WHERE tag_id = :source"),
        {"source": source_tag_id, "target": target_tag_id},
    )


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


def _free_name(session: Session, label: str) -> str:
    """`label` as a topic name, or with " (tag)" / " (tag 2)" ... added if it is taken."""
    base = normalize_topic_name(label)
    candidates = (base, f"{base} (tag)", *(f"{base} (tag {n})" for n in range(2, 100)))
    for name in candidates:
        if (
            session.execute(text("SELECT 1 FROM topics WHERE name = :name"), {"name": name}).first()
            is None
        ):
            return name
    raise DuplicateTopicError(f"There are too many topics named like {label!r}")


def _require_tag(session: Session, tag_id: int) -> "Tag":
    from homefeed_core.tags import Tag

    row = session.execute(
        text("SELECT id, slug, label FROM tags WHERE id = :id"), {"id": tag_id}
    ).one_or_none()
    if row is None:
        raise ValueError(f"There is no tag with id {tag_id}")
    return Tag(*row)


def _check_match_mode(match_mode: str, tag: "Tag | None") -> MatchMode:
    mode = normalize_match_mode(match_mode)
    if tag is None and mode != "embedding":
        raise ValueError(f"A topic without a tag can only match by embedding, not {mode!r}")
    return mode


def _check_tag_free(session: Session, tag_id: int) -> None:
    if topic_for_tag(session, tag_id) is not None:
        raise DuplicateTopicError("This tag already has a topic")


def _check_name_free(session: Session, name: str, *, other_than: int | None = None) -> None:
    taken = session.execute(
        text("SELECT 1 FROM topics WHERE name = :name AND id IS NOT :id"),
        {"name": name, "id": other_than},
    ).first()
    if taken is not None:
        raise DuplicateTopicError(f"There is already a topic named {name!r}")


def _topic(row: Sequence[Any], now: datetime) -> Topic:
    (
        topic_id,
        name,
        description,
        weight,
        decay,
        reaffirmed_at,
        created_at,
        updated_at,
        match_mode,
        tag_id,
        tag_slug,
        tag_label,
        hide,
    ) = row
    return Topic(
        id=topic_id,
        name=name,
        description=description,
        weight=weight,
        decay=bool(decay),
        match_mode=match_mode,
        hide=bool(hide),
        tag_id=tag_id,
        tag_slug=tag_slug,
        tag_label=tag_label,
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
