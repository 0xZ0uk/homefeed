"""Specific tags for videos (`rust`, `woodworking`, `f1`) and their canonical vocabulary.

A tag has a slug, its normalized and unique key (`slugify`: lowercase words joined by
hyphens, accents dropped, `c++` as `c-plus-plus`), and a label to show. Other spellings
map to a tag through `tag_aliases`, so variants of one idea share a tag.

`resolve_tag(session, text)` turns any spelling into its canonical tag, in this order:

1. a tag whose slug is the text's slug;
2. an alias with that slug;
3. a tag or alias spelled the same apart from hyphens (`wood-working` is
   `woodworking`, `node-js` is `nodejs`); the new spelling is recorded as an alias;
4. when an embedder is passed, the existing tag whose embedding is most similar to the
   text's, if the cosine similarity reaches the threshold (`TAG_MERGE_THRESHOLD`,
   0.92 by default); the spelling is recorded as an alias, as in 3;
5. otherwise, a new tag labelled with the text (and embedded, if there is an embedder).

Aliases are checked before embeddings, so an alias made by hand (source 'user') always
wins over a similarity match.

Every tag stores the embedding of its label and the model that made it (the same model
as videos and topics). A tag without one (made before embeddings existed, or while the
embedder failed) just doesn't take part in step 4; `refresh_tag_embeddings` gives it one,
and re-embeds all after an `EMBEDDING_MODEL` change (the worker calls it).

Videos link to tags in `video_tags`, with a source: `llm` (proposed by the tagger in
homefeed_core.llm_tags, with the model's confidence and the prompt version) or `manual`
(added by hand, confidence 1). `set_llm_tags` replaces a video's LLM links on each
retagging and leaves manual links alone. A link with `removed_at` set is a tombstone,
removed by hand (`remove_video_tag`): retagging never brings it back, and readers
(`get_video_tags`) skip it. `add_manual_tag` adds a tag by hand, clearing a tombstone.
"""

import logging
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from homefeed_core.curation import relink_tag_topic
from homefeed_core.embeddings import Embedding, EmbeddingProvider, serialize_embedding
from homefeed_core.gateway.events import format_timestamp

logger = logging.getLogger(__name__)

# Longer proposals are sentences, not tags.
LABEL_MAX_LENGTH = 50

# Cosine similarity from which a proposed tag is another spelling of an existing one.
# Conservative: a wrong merge hides a distinction, a missed one only leaves a duplicate
# for the user to merge by hand. Measured with bge-small-en-v1.5 on short labels:
# plurals and spelling variants score 0.93+ ("formula 1" / "formula one" 0.96), but
# related, distinct tags reach 0.90 ("nba" / "basketball"), and abbreviations often
# score lower than that ("js" / "javascript" 0.87), so those are left to the prompt's
# list of existing tags and to merges by hand.
DEFAULT_MERGE_THRESHOLD = 0.92

TagSource = Literal["llm", "manual"]


@dataclass(frozen=True)
class Tag:
    id: int
    slug: str
    label: str


@dataclass(frozen=True)
class ProposedTag:
    """A tag as proposed for a video (by the LLM, or typed by hand), before resolution."""

    label: str
    confidence: float  # 0 to 1


@dataclass(frozen=True)
class VideoTag:
    """A tag on a video."""

    tag_id: int
    slug: str
    label: str
    source: TagSource
    confidence: float  # 1 for manual tags


def slugify(value: str) -> str:
    """The slug of a tag spelling: lowercase, accents dropped, words joined by hyphens
    ("Dovetail Joints" -> "dovetail-joints", "Pokémon" -> "pokemon", "C++" ->
    "c-plus-plus"). Empty when nothing is left (e.g. only punctuation)."""
    value = unicodedata.normalize("NFKD", value.strip().lstrip("#"))
    # Only Latin diacritics: other combining marks (e.g. kana voicing) change the letter.
    value = unicodedata.normalize("NFC", re.sub("[̀-ͯ]", "", value)).casefold()
    value = re.sub("['’]", "", value)  # "women's" -> "womens"
    value = value.replace("&", " and ").replace("+", " plus ").replace("#", " sharp ")
    return re.sub(r"[\W_]+", "-", value).strip("-")


def clean_label(value: str) -> str:
    """How a proposed spelling is shown: whitespace collapsed, a leading "#" dropped."""
    return " ".join(value.strip().lstrip("#").split())


def is_usable(value: str) -> bool:
    """Whether `value` can be a tag: it has a slug and isn't over-long."""
    label = clean_label(value)
    return bool(slugify(label)) and len(label) <= LABEL_MAX_LENGTH


def get_tag(session: Session, slug: str) -> Tag | None:
    """The tag with this exact slug, or None."""
    row = session.execute(
        text("SELECT id, slug, label FROM tags WHERE slug = :slug"), {"slug": slug}
    ).one_or_none()
    return None if row is None else Tag(*row)


def find_tag(session: Session, value: str) -> Tag | None:
    """The existing tag `value` resolves to by slug, alias or spelling (steps 1 to 3 of
    `resolve_tag`), without writing anything; None when it would be a new tag or needs an
    embedding to decide."""
    tag, _ = _match(session, slugify(clean_label(value)))
    return tag


def resolve_tag(
    session: Session,
    value: str,
    *,
    embedder: EmbeddingProvider | None = None,
    threshold: float = DEFAULT_MERGE_THRESHOLD,
    embedding: Embedding | None = None,
    now: datetime | None = None,
) -> Tag | None:
    """The canonical tag for a spelling, found or created (see the module docstring).
    None when `value` isn't usable as a tag (`is_usable`).

    With an `embedder`, spellings without a slug or alias match are embedded and matched
    by similarity (`threshold`), and a new tag is stored with its embedding. `embedding`
    is the vector of the cleaned label when the caller has embedded it already (in a
    batch, see `set_llm_tags`). If embedding fails, the tag is resolved without it."""
    if not is_usable(value):
        return None
    label = clean_label(value)
    slug = slugify(label)
    tag, needs_alias = _match(session, slug)
    if tag is None and embedder is not None:
        if embedding is None:
            embedding = _embed_labels(embedder, [label])[0]
        if embedding is not None:
            tag = _match_embedding(session, embedder, embedding, threshold)
            needs_alias = tag is not None
    if tag is not None:
        if needs_alias:
            _add_alias(session, slug, tag, now=now)
        return tag
    row = session.execute(
        text(
            """
            INSERT INTO tags (slug, label, embedding, embedding_model, created_at, updated_at)
            VALUES (:slug, :label, :embedding, :model, :now, :now)
            RETURNING id
            """
        ),
        {
            "slug": slug,
            "label": label,
            "embedding": None if embedding is None else serialize_embedding(embedding),
            "model": None if embedding is None or embedder is None else embedder.model,
            "now": format_timestamp(now or datetime.now(UTC)),
        },
    ).one()
    return Tag(row[0], slug, label)


def _match(session: Session, slug: str) -> tuple[Tag | None, bool]:
    """(existing tag for `slug` by slug, alias or spelling, whether `slug` should become
    an alias of it)."""
    if not slug:
        return None, False
    tag = get_tag(session, slug)
    if tag is not None:
        return tag, False
    row = session.execute(
        text(
            """
            SELECT t.id, t.slug, t.label FROM tag_aliases AS a JOIN tags AS t ON t.id = a.tag_id
            WHERE a.alias = :slug
            """
        ),
        {"slug": slug},
    ).one_or_none()
    if row is not None:
        return Tag(*row), False
    # Spelled the same apart from hyphens. The oldest tag wins if several do.
    row = session.execute(
        text(
            """
            SELECT id, slug, label FROM tags WHERE replace(slug, '-', '') = :compact
            UNION ALL
            SELECT t.id, t.slug, t.label FROM tag_aliases AS a JOIN tags AS t ON t.id = a.tag_id
            WHERE replace(a.alias, '-', '') = :compact
            ORDER BY id LIMIT 1
            """
        ),
        {"compact": slug.replace("-", "")},
    ).one_or_none()
    if row is not None:
        return Tag(*row), True
    return None, False


def _match_embedding(
    session: Session, embedder: EmbeddingProvider, embedding: Embedding, threshold: float
) -> Tag | None:
    """The tag embedded by `embedder`'s model most similar to `embedding`, if it reaches
    `threshold`. Tags without an embedding, or with one of another model, are skipped."""
    row = session.execute(
        text(
            """
            SELECT id, slug, label, 1.0 - vec_distance_cosine(embedding, :embedding) AS similarity
            FROM tags WHERE embedding_model = :model AND embedding IS NOT NULL
            ORDER BY similarity DESC, id LIMIT 1
            """
        ),
        {"embedding": serialize_embedding(embedding), "model": embedder.model},
    ).one_or_none()
    if row is None or row.similarity < threshold:
        return None
    return Tag(row.id, row.slug, row.label)


def _embed_labels(embedder: EmbeddingProvider, labels: Sequence[str]) -> list[Embedding | None]:
    """One embedding per label in a single call, or Nones if the embedder fails (tags
    then work without embeddings until `refresh_tag_embeddings`)."""
    if not labels:
        return []
    try:
        vectors = embedder.embed(labels)
    except Exception:
        logger.exception("Could not embed %d tag labels; resolving without embeddings", len(labels))
        return [None] * len(labels)
    return list(vectors)


def refresh_tag_embeddings(session: Session, embedder: EmbeddingProvider) -> list[int]:
    """Embed the labels of tags without an embedding from `embedder`'s model: new ones
    made without an embedder, and all after an `EMBEDDING_MODEL` change. Returns the ids
    of the tags embedded."""
    rows = session.execute(
        text(
            """
            SELECT id, label FROM tags
            WHERE embedding IS NULL OR embedding_model IS NOT :model ORDER BY id
            """
        ),
        {"model": embedder.model},
    ).all()
    if not rows:
        return []
    vectors = embedder.embed([label for _, label in rows])
    session.execute(
        text("UPDATE tags SET embedding = :embedding, embedding_model = :model WHERE id = :id"),
        [
            {"id": tag_id, "embedding": serialize_embedding(vector), "model": embedder.model}
            for (tag_id, _), vector in zip(rows, vectors, strict=True)
        ],
    )
    return [tag_id for tag_id, _ in rows]


def top_tag_labels(session: Session, limit: int) -> list[str]:
    """The labels of the `limit` tags on the most videos (removed links don't count),
    alphabetical so the same set always reads the same."""
    rows = session.execute(
        text(
            """
            SELECT t.label FROM tags AS t JOIN video_tags AS vt ON vt.tag_id = t.id
            WHERE vt.removed_at IS NULL
            GROUP BY t.id ORDER BY count(*) DESC, t.id LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    return sorted((label for (label,) in rows), key=lambda label: (label.casefold(), label))


def _add_alias(session: Session, alias: str, tag: Tag, *, now: datetime | None = None) -> None:
    """Record `alias` (a slug) as another spelling of `tag`, found automatically."""
    session.execute(
        text(
            """
            INSERT INTO tag_aliases (alias, tag_id, source, created_at)
            VALUES (:alias, :tag_id, 'auto', :now)
            ON CONFLICT (alias) DO NOTHING
            """
        ),
        {"alias": alias, "tag_id": tag.id, "now": format_timestamp(now or datetime.now(UTC))},
    )


def set_llm_tags(
    session: Session,
    video_id: str,
    proposals: Sequence[ProposedTag],
    *,
    prompt_version: int,
    embedder: EmbeddingProvider | None = None,
    threshold: float = DEFAULT_MERGE_THRESHOLD,
    now: datetime | None = None,
) -> list[Tag]:
    """Make `proposals` the LLM tags of `video_id`, resolving each to its canonical tag.

    LLM links the proposals no longer include are dropped. Manual links and tombstones
    are kept as they are: a proposal for a tag the user added or removed by hand changes
    nothing. Proposals resolving to the same tag keep the highest confidence. Returns
    the resolved tags, most confident first.

    With an `embedder`, the proposals that need an embedding to resolve are embedded
    together in one call (see `resolve_tag`).
    """
    timestamp = format_timestamp(now or datetime.now(UTC))
    confidences: dict[int, float] = {}
    resolved: dict[int, Tag] = {}
    ranked = sorted(proposals, key=lambda p: -p.confidence)
    embeddings: dict[str, Embedding | None] = {}
    if embedder is not None:
        unmatched = list(
            dict.fromkeys(
                clean_label(p.label)
                for p in ranked
                if is_usable(p.label) and find_tag(session, p.label) is None
            )
        )
        embeddings = dict(zip(unmatched, _embed_labels(embedder, unmatched), strict=True))
    for proposal in ranked:
        label = clean_label(proposal.label)
        tag = resolve_tag(
            session,
            proposal.label,
            # Without a vector (the batch failed) a proposal is resolved without
            # embeddings rather than embedded again one by one.
            embedder=embedder if embeddings.get(label) is not None else None,
            threshold=threshold,
            embedding=embeddings.get(label),
            now=now,
        )
        if tag is None or tag.id in resolved:
            continue
        resolved[tag.id] = tag
        confidences[tag.id] = min(1.0, max(0.0, proposal.confidence))
    session.execute(
        text(
            """
            DELETE FROM video_tags
            WHERE video_id = :video_id AND source = 'llm' AND removed_at IS NULL
              AND tag_id NOT IN :tag_ids
            """
        ).bindparams(bindparam("tag_ids", expanding=True)),
        # An empty IN list would match nothing; -1 is no tag id.
        {"video_id": video_id, "tag_ids": list(resolved) or [-1]},
    )
    for tag_id, confidence in confidences.items():
        session.execute(
            text(
                """
                INSERT INTO video_tags (video_id, tag_id, source, confidence, prompt_version,
                                        tagged_at)
                VALUES (:video_id, :tag_id, 'llm', :confidence, :version, :now)
                ON CONFLICT (video_id, tag_id) DO UPDATE SET
                    confidence = excluded.confidence,
                    prompt_version = excluded.prompt_version,
                    tagged_at = excluded.tagged_at
                WHERE video_tags.source = 'llm' AND video_tags.removed_at IS NULL
                """
            ),
            {
                "video_id": video_id,
                "tag_id": tag_id,
                "confidence": confidence,
                "version": prompt_version,
                "now": timestamp,
            },
        )
    return list(resolved.values())


def get_video_tags(session: Session, video_ids: Iterable[str]) -> dict[str, list[VideoTag]]:
    """The tags of each video, most confident first (manual tags count as 1), without
    removed ones. Videos without tags are left out."""
    ids = list(dict.fromkeys(video_ids))
    if not ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT vt.video_id, t.id, t.slug, t.label, vt.source, vt.confidence
            FROM video_tags AS vt JOIN tags AS t ON t.id = vt.tag_id
            WHERE vt.video_id IN :ids AND vt.removed_at IS NULL
            ORDER BY vt.video_id, vt.confidence DESC, t.label
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    )
    result: dict[str, list[VideoTag]] = {}
    for video_id, tag_id, slug, label, source, confidence in rows:
        result.setdefault(video_id, []).append(
            VideoTag(tag_id, slug, label, cast(TagSource, source), confidence)
        )
    return result


DEFAULT_TAG_LIMIT = 50
MAX_TAG_LIMIT = 200
TAG_QUERY_MAX_LENGTH = 100

DEFAULT_TAG_VIDEOS_LIMIT = 24
MAX_TAG_VIDEOS_LIMIT = 100


@dataclass(frozen=True)
class TagSummary:
    """A tag with how many videos carry it."""

    id: int
    slug: str
    label: str
    video_count: int  # videos with a live (not removed) link, from any source


@dataclass(frozen=True)
class TagVideo:
    """A video carrying a tag, with what a video card shows."""

    video_id: str
    title: str
    duration_seconds: int | None
    published_at: str | None  # ISO 8601 UTC
    thumbnail_url: str | None
    view_count: int | None
    channel_id: str
    channel_title: str
    channel_thumbnail_url: str | None
    watched: bool  # played or rated, as in the feed's `FeedItem.watched`


def resolve_slug(session: Session, slug: str) -> Tag | None:
    """The canonical tag for a slug that may be an alias (`rust-lang` -> `rust`), or None
    when it is neither a tag nor an alias. Unlike `resolve_tag`, writes nothing."""
    tag = get_tag(session, slug)
    if tag is not None:
        return tag
    row = session.execute(
        text(
            """
            SELECT t.id, t.slug, t.label
            FROM tag_aliases AS a JOIN tags AS t ON t.id = a.tag_id
            WHERE a.alias = :slug
            """
        ),
        {"slug": slug},
    ).one_or_none()
    return None if row is None else Tag(*row)


def list_tags(
    session: Session,
    query: str | None = None,
    *,
    limit: int = DEFAULT_TAG_LIMIT,
    offset: int = 0,
) -> list[TagSummary]:
    """Tags carried by at least one video, most videos first (then by label), each with
    its video count. With `query`, only tags whose slug or an alias contains the query's
    slug (`Dovetail Joints` finds `dovetail-joints`); tags no video carries are left out."""
    needle = slugify(query or "")
    rows = session.execute(
        text(
            """
            SELECT t.id, t.slug, t.label, count(*) AS n
            FROM tags AS t JOIN video_tags AS vt ON vt.tag_id = t.id
            WHERE vt.removed_at IS NULL
              AND (:needle = '' OR instr(t.slug, :needle) > 0
                   OR EXISTS (SELECT 1 FROM tag_aliases AS a
                              WHERE a.tag_id = t.id AND instr(a.alias, :needle) > 0))
            GROUP BY t.id
            ORDER BY n DESC, t.label, t.id
            LIMIT :limit OFFSET :offset
            """
        ),
        {"needle": needle, "limit": limit, "offset": offset},
    )
    return [TagSummary(*row) for row in rows]


def count_tag_videos(session: Session, tag_id: int) -> int:
    """How many videos carry the tag (not counting removed links)."""
    return session.execute(
        text("SELECT count(*) FROM video_tags WHERE tag_id = :tag_id AND removed_at IS NULL"),
        {"tag_id": tag_id},
    ).scalar_one()


def list_tag_videos(
    session: Session,
    tag_id: int,
    *,
    limit: int = DEFAULT_TAG_VIDEOS_LIMIT,
    offset: int = 0,
) -> list[TagVideo]:
    """The videos carrying the tag from any source, newest published first (videos with no
    publish date last), without removed links."""
    rows = session.execute(
        text(
            """
            SELECT v.id, v.title, v.duration_seconds, v.published_at, v.thumbnail_url,
                   v.view_count, c.id, c.title, c.thumbnail_url,
                   EXISTS (SELECT 1 FROM ratings AS r WHERE r.video_id = v.id)
                   OR EXISTS (
                       SELECT 1 FROM watch_events AS w
                       WHERE w.video_id = v.id AND w.event_type = 'play'
                   )
            FROM video_tags AS vt
            JOIN videos AS v ON v.id = vt.video_id
            JOIN channels AS c ON c.id = v.channel_id
            WHERE vt.tag_id = :tag_id AND vt.removed_at IS NULL
            ORDER BY v.published_at IS NULL, v.published_at DESC, v.id
            LIMIT :limit OFFSET :offset
            """
        ),
        {"tag_id": tag_id, "limit": limit, "offset": offset},
    )
    return [
        TagVideo(
            video_id=row[0],
            title=row[1],
            duration_seconds=row[2],
            published_at=row[3],
            thumbnail_url=row[4],
            view_count=row[5],
            channel_id=row[6],
            channel_title=row[7],
            channel_thumbnail_url=row[8],
            watched=bool(row[9]),
        )
        for row in rows
    ]


def add_manual_tag(
    session: Session, video_id: str, value: str, *, now: datetime | None = None
) -> Tag | None:
    """Tag `video_id` by hand with `value`, resolved like an LLM proposal (`resolve_tag`).

    The link is `manual` with confidence 1, whatever it was before: an LLM link becomes
    manual (so retagging keeps it) and a tombstone is cleared. None when `value` isn't
    usable as a tag. The video must exist.
    """
    tag = resolve_tag(session, value, now=now)
    if tag is None:
        return None
    session.execute(
        text(
            """
            INSERT INTO video_tags (video_id, tag_id, source, confidence, prompt_version,
                                    tagged_at, removed_at)
            VALUES (:video_id, :tag_id, 'manual', 1, NULL, :now, NULL)
            ON CONFLICT (video_id, tag_id) DO UPDATE SET
                source = 'manual',
                confidence = 1,
                prompt_version = NULL,
                tagged_at = excluded.tagged_at,
                removed_at = NULL
            """
        ),
        {"video_id": video_id, "tag_id": tag.id, "now": format_timestamp(now or datetime.now(UTC))},
    )
    return tag


def remove_video_tag(
    session: Session, video_id: str, slug: str, *, now: datetime | None = None
) -> bool:
    """Remove the tag with this slug from `video_id` by hand, leaving a tombstone so that
    retagging never adds it back (manual links are tombstoned too). False when the video
    has no such tag, or it was already removed."""
    result = session.execute(
        text(
            """
            UPDATE video_tags SET removed_at = :now
            WHERE video_id = :video_id AND removed_at IS NULL
              AND tag_id = (SELECT id FROM tags WHERE slug = :slug)
            """
        ),
        {"video_id": video_id, "slug": slug, "now": format_timestamp(now or datetime.now(UTC))},
    )
    return result.rowcount > 0  # type: ignore[attr-defined]


@dataclass(frozen=True)
class TagSuggestion:
    slug: str
    label: str
    video_count: int  # videos currently carrying the tag


def suggest_tags(session: Session, query: str, *, limit: int = 8) -> list[TagSuggestion]:
    """Existing tags to offer while typing `query`: those whose slug or an alias contains
    the query's slug, prefix matches first, then the most used. Without a query, the most
    used tags."""
    slug = slugify(clean_label(query))
    escaped = slug.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = session.execute(
        text(
            """
            SELECT t.slug, t.label,
                   (SELECT count(*) FROM video_tags AS vt
                    WHERE vt.tag_id = t.id AND vt.removed_at IS NULL) AS video_count
            FROM tags AS t
            WHERE :slug = ''
               OR t.slug LIKE '%' || :escaped || '%' ESCAPE '\\'
               OR EXISTS (SELECT 1 FROM tag_aliases AS a
                          WHERE a.tag_id = t.id AND a.alias LIKE '%' || :escaped || '%' ESCAPE '\\')
            ORDER BY t.slug LIKE :escaped || '%' ESCAPE '\\' DESC, video_count DESC, t.slug
            LIMIT :limit
            """
        ),
        {"slug": slug, "escaped": escaped, "limit": limit},
    )
    return [TagSuggestion(*row) for row in rows]


class DuplicateTagError(ValueError):
    """The slug is already another tag's, or another tag's alias: merge the tags instead
    (or split the alias out first)."""


class SameTagError(ValueError):
    """A tag can't be merged into itself."""


@dataclass(frozen=True)
class TagAlias:
    alias: str  # a slug
    source: Literal["auto", "user"]


@dataclass(frozen=True)
class AdminTag:
    """A tag with what the Curation tab shows: its videos and other spellings."""

    id: int
    slug: str
    label: str
    video_count: int  # videos linked, removed links excluded
    aliases: list[TagAlias]


def _tag_by_id(session: Session, tag_id: int) -> Tag | None:
    row = session.execute(
        text("SELECT id, slug, label FROM tags WHERE id = :id"), {"id": tag_id}
    ).one_or_none()
    return None if row is None else Tag(*row)


def _slug_owner(session: Session, slug: str) -> int | None:
    """The id of the tag that has `slug` as its slug or as an alias, or None."""
    row = session.execute(
        text(
            """
            SELECT id FROM tags WHERE slug = :slug
            UNION ALL SELECT tag_id FROM tag_aliases WHERE alias = :slug
            """
        ),
        {"slug": slug},
    ).first()
    return None if row is None else row[0]


def _embed_label(embedder: EmbeddingProvider | None, label: str) -> tuple[bytes | None, str | None]:
    """(serialized embedding, model) of `label`; both None without an embedder, or if it
    fails (the worker's `refresh_tag_embeddings` embeds the tag later)."""
    if embedder is None:
        return None, None
    vector = _embed_labels(embedder, [label])[0]
    if vector is None:
        return None, None
    return serialize_embedding(vector), embedder.model


def _put_user_alias(session: Session, alias: str, tag_id: int, now: str) -> None:
    """Make `alias` a user alias of `tag_id`, taking it over from any tag that has it."""
    session.execute(
        text(
            """
            INSERT INTO tag_aliases (alias, tag_id, source, created_at)
            VALUES (:alias, :tag_id, 'user', :now)
            ON CONFLICT (alias) DO UPDATE SET tag_id = excluded.tag_id, source = 'user'
            """
        ),
        {"alias": alias, "tag_id": tag_id, "now": now},
    )


def rename_tag(
    session: Session,
    tag_id: int,
    label: str,
    *,
    embedder: EmbeddingProvider | None = None,
    now: datetime | None = None,
) -> Tag | None:
    """Give a tag a new label, and the slug that goes with it. None if there is no such tag.

    The old slug becomes a 'user' alias of the tag, so proposals and links using the old
    spelling still resolve to it. The label is embedded again if there is an `embedder`;
    otherwise (or if embedding fails) the embedding is cleared, so the worker's
    `refresh_tag_embeddings` makes a fresh one and the old label's vector never matches.
    A new slug that is another tag's slug or alias raises `DuplicateTagError`: merge
    the tags instead. If it is an alias of this very tag, the alias is dropped (a slug
    is never both). A change of case or spacing only keeps the slug and changes the label.
    Raises ValueError for a label that isn't usable (`is_usable`)."""
    if not is_usable(label):
        raise ValueError(
            f"A tag label needs letters or digits and at most {LABEL_MAX_LENGTH} characters"
        )
    tag = _tag_by_id(session, tag_id)
    if tag is None:
        return None
    label = clean_label(label)
    slug = slugify(label)
    timestamp = format_timestamp(now or datetime.now(UTC))
    if slug != tag.slug:
        owner = _slug_owner(session, slug)
        if owner is not None and owner != tag.id:
            raise DuplicateTagError(
                f"“{label}” is already another tag; merge the tags instead of renaming"
            )
        session.execute(text("DELETE FROM tag_aliases WHERE alias = :slug"), {"slug": slug})
        _put_user_alias(session, tag.slug, tag.id, timestamp)
    embedding, model = _embed_label(embedder, label)
    session.execute(
        text(
            """
            UPDATE tags SET slug = :slug, label = :label, embedding = :embedding,
                            embedding_model = :model, updated_at = :now
            WHERE id = :id
            """
        ),
        {
            "id": tag.id,
            "slug": slug,
            "label": label,
            "embedding": embedding,
            "model": model,
            "now": timestamp,
        },
    )
    return Tag(tag.id, slug, label)


def merge_tags(
    session: Session, source_id: int, target_id: int, *, now: datetime | None = None
) -> Tag | None:
    """Fold the source tag into the target and delete it. Returns the target, or None if
    either tag doesn't exist. Raises `SameTagError` for a tag and itself.

    Spellings: the source's slug and all its aliases become 'user' aliases of the target,
    so they resolve to it from now on, before any embedding match.

    Subscriptions: the source's tag-backed topic moves to the target, unless the target
    has one already, which stands (`curation.relink_tag_topic`).

    Video links move to the target. A video linked to both keeps one link, by these
    rules in order:
    - a manual link (added by hand, not removed) wins: the user said the video is about it;
    - otherwise a tombstone (removed by hand) wins over an LLM link, so it stays removed;
    - otherwise the higher confidence wins (the target's on a tie).
    The winner is the whole link (source, confidence, prompt version, time).
    """
    if source_id == target_id:
        raise SameTagError("A tag can't be merged into itself")
    source = _tag_by_id(session, source_id)
    target = _tag_by_id(session, target_id)
    if source is None or target is None:
        return None
    timestamp = format_timestamp(now or datetime.now(UTC))
    # Aliases first: deleting the source would cascade them away.
    session.execute(
        text("UPDATE tag_aliases SET tag_id = :target, source = 'user' WHERE tag_id = :source"),
        {"source": source.id, "target": target.id},
    )
    _put_user_alias(session, source.slug, target.id, timestamp)
    # The source's subscription follows it (deleting the tag would cascade it away).
    relink_tag_topic(session, source.id, target.id)
    rows = session.execute(
        text(
            """
            SELECT s.video_id,
                   s.removed_at IS NOT NULL, s.source = 'manual', s.confidence,
                   t.video_id IS NOT NULL,
                   t.removed_at IS NOT NULL, t.source = 'manual', t.confidence
            FROM video_tags AS s LEFT JOIN video_tags AS t
              ON t.video_id = s.video_id AND t.tag_id = :target
            WHERE s.tag_id = :source
            """
        ),
        {"source": source.id, "target": target.id},
    ).all()
    for (
        video_id,
        s_removed,
        s_manual,
        s_confidence,
        linked,
        t_removed,
        t_manual,
        t_confidence,
    ) in rows:
        if linked:  # linked to the target too: the better link stays
            if _link_rank(s_removed, s_manual, s_confidence) > _link_rank(
                t_removed, t_manual, t_confidence
            ):
                session.execute(
                    text("DELETE FROM video_tags WHERE video_id = :video AND tag_id = :target"),
                    {"video": video_id, "target": target.id},
                )
            else:
                continue  # the target's own link wins; the source's goes with the source
        session.execute(
            text("UPDATE video_tags SET tag_id = :target WHERE video_id = :video AND tag_id = :s"),
            {"video": video_id, "target": target.id, "s": source.id},
        )
    session.execute(text("DELETE FROM tags WHERE id = :id"), {"id": source.id})
    session.execute(
        text("UPDATE tags SET updated_at = :now WHERE id = :id"),
        {"id": target.id, "now": timestamp},
    )
    return target


def _link_rank(removed: bool, manual: bool, confidence: float) -> tuple[bool, bool, float]:
    """How `merge_tags` ranks two links of one video: active manual, then tombstone, then
    confidence."""
    return (bool(manual) and not removed, bool(removed), confidence)


def split_alias(
    session: Session,
    alias: str,
    *,
    embedder: EmbeddingProvider | None = None,
    now: datetime | None = None,
) -> Tag | None:
    """Detach an alias from its tag into a tag of its own, labelled from the alias
    ("node-js" -> "node js"; rename it afterwards for a nicer label). Returns the new
    tag, or None if there is no such alias.

    Video links stay where they are: nothing records which videos meant the alias, so
    the new tag starts without videos and gets them from future tagging.

    Splits win over automatic matching. The alias row is deleted and the new tag takes
    its slug, and slug lookup comes before aliases and embeddings in `resolve_tag`, so
    this spelling resolves to the new tag from now on. The new tag is embedded from its
    own label (with an `embedder`; otherwise the worker does it), so similar spellings
    can match it by similarity, and the old tag's embedding is untouched."""
    row = session.execute(
        text("SELECT tag_id FROM tag_aliases WHERE alias = :alias"), {"alias": alias}
    ).one_or_none()
    if row is None:
        return None
    if get_tag(session, alias) is not None:  # can't happen: an alias is never a slug
        raise DuplicateTagError(f"“{alias}” is already a tag")
    label = alias.replace("-", " ")
    embedding, model = _embed_label(embedder, label)
    session.execute(text("DELETE FROM tag_aliases WHERE alias = :alias"), {"alias": alias})
    new_id = session.execute(
        text(
            """
            INSERT INTO tags (slug, label, embedding, embedding_model, created_at, updated_at)
            VALUES (:slug, :label, :embedding, :model, :now, :now)
            RETURNING id
            """
        ),
        {
            "slug": alias,
            "label": label,
            "embedding": embedding,
            "model": model,
            "now": format_timestamp(now or datetime.now(UTC)),
        },
    ).scalar_one()
    return Tag(new_id, alias, label)


def _like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_admin_tags(
    session: Session, query: str | None = None, *, limit: int = 200
) -> list[AdminTag]:
    """Tags with video counts and aliases, most videos first (then by label). `query`
    keeps the tags whose label, slug or an alias contains it, ignoring case and treating
    spaces as hyphens for slugs and aliases."""
    where = ""
    params: dict[str, object] = {"limit": limit}
    needle = (query or "").strip()
    if needle:
        where = r"""
            WHERE t.label LIKE :q ESCAPE '\' OR t.slug LIKE :slug ESCAPE '\'
               OR EXISTS (SELECT 1 FROM tag_aliases AS a
                          WHERE a.tag_id = t.id AND a.alias LIKE :slug ESCAPE '\')
            """
        params["q"] = _like_pattern(needle)
        params["slug"] = _like_pattern(slugify(needle) or needle.casefold())
    rows = session.execute(
        text(
            f"""
            SELECT t.id, t.slug, t.label,
                   (SELECT count(*) FROM video_tags AS vt
                    WHERE vt.tag_id = t.id AND vt.removed_at IS NULL) AS video_count
            FROM tags AS t {where}
            ORDER BY video_count DESC, t.label COLLATE NOCASE, t.id LIMIT :limit
            """  # noqa: S608 - `where` is fixed text; values are bound
        ),
        params,
    ).all()
    by_tag: dict[int, list[TagAlias]] = {row.id: [] for row in rows}
    if by_tag:
        for tag_id, alias, source in session.execute(
            text(
                "SELECT tag_id, alias, source FROM tag_aliases WHERE tag_id IN :ids ORDER BY alias"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": list(by_tag)},
        ):
            by_tag[tag_id].append(TagAlias(alias, cast(Literal["auto", "user"], source)))
    return [AdminTag(row.id, row.slug, row.label, row.video_count, by_tag[row.id]) for row in rows]
