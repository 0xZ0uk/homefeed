"""Videos like one video, for the watch page's "Find more like this" button.

Nothing here runs unasked: the watch page calls it when the button is pressed, so a video
that ends never leads on to a suggestion.

Where the videos come from:
- `related` candidates attributed to the video: `candidates.RelatedVideosSource` stores
  what YouTube suggests next to each top-tier rated video, with the seed's id as
  `source_detail`. Their reason is "Related on YouTube".
- Its nearest neighbours in `video_embeddings` by cosine similarity (see `embeddings`),
  from the embedding model's similarity floor up (`embeddings.calibration`): below it the
  ranker treats videos as unrelated too. Their reason is "Similar to this video".

A video found both ways counts as related. Results are ranked by cosine similarity to the
video, best first. A related video that has no similarity (it isn't embedded yet, or the
video itself isn't) goes after those that do, newest first.

What the feed hides stays hidden: videos already watched (played or rated) or dismissed,
and whatever `ranker.filter_reason` drops (muted channels, muted keywords, hidden tags,
Shorts, live streams, durations outside the user's bounds). Channels hidden from Discover,
of either kind, are left out as well.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Row, bindparam, text
from sqlalchemy.orm import Session

from homefeed_core import channel_hides
from homefeed_core.candidates import RELATED
from homefeed_core.config import Settings, get_settings
from homefeed_core.curation import list_tag_subscriptions, muted_keywords
from homefeed_core.embeddings import (
    Embedding,
    calibration,
    cosine_similarity,
    get_embedding,
    get_embeddings,
    serialize_embedding,
)
from homefeed_core.feeds import dismissed_video_ids, load_curation, watched_video_ids
from homefeed_core.ranker import (
    ChannelCuration,
    DurationBounds,
    History,
    KeywordMutes,
    RankCandidate,
    filter_reason,
)
from homefeed_core.tags import get_video_tags
from homefeed_core.user_settings import get_user_settings

DEFAULT_SIMILAR_LIMIT = 8
MAX_SIMILAR_LIMIT = 24

RELATED_REASON = "Related on YouTube"
SIMILAR_REASON = "Similar to this video"

# Neighbours are read, and checked against the filters, this many at a time.
_BATCH_SIZE = 32


@dataclass(frozen=True)
class SimilarVideo:
    video_id: str
    title: str
    duration_seconds: int | None
    published_at: str | None  # ISO 8601 UTC
    thumbnail_url: str | None
    view_count: int | None
    channel_id: str
    channel_title: str
    channel_thumbnail_url: str | None
    watched: bool  # always False, as watched videos are left out; it completes the card's shape
    reason: str  # RELATED_REASON or SIMILAR_REASON
    similarity: float | None  # cosine similarity to the video; None when unknown


def similar_videos(
    session: Session,
    video_id: str,
    limit: int = DEFAULT_SIMILAR_LIMIT,
    *,
    settings: Settings | None = None,
) -> list[SimilarVideo]:
    """Up to `limit` videos like `video_id`, best first (see the module docstring).

    Empty when nothing qualifies, e.g. while neither the video nor anything near it has an
    embedding and YouTube's related videos were never fetched."""
    if limit < 1:
        return []
    settings = settings or get_settings()
    rules = _Rules.load(session, settings)
    seed = get_embedding(session, video_id)
    related = _related_video_ids(session, video_id)

    # Insertion order is the tie-break, below: related videos, then neighbours by closeness.
    found: dict[str, SimilarVideo] = {}
    vectors = get_embeddings(session, related) if seed is not None else {}
    for related_id, row in rules.admitted(session, related).items():
        vector = vectors.get(related_id)
        found[related_id] = _video(
            row,
            RELATED_REASON,
            None if seed is None or vector is None else cosine_similarity(seed, vector),
        )

    if seed is not None:
        floor = calibration(settings).similarity_floor
        already = set(related)
        neighbours = 0
        for batch in _nearest(session, seed, video_id, floor):
            closeness = {id_: score for id_, score in batch if id_ not in already}
            for neighbour_id, row in rules.admitted(session, list(closeness)).items():
                found[neighbour_id] = _video(row, SIMILAR_REASON, closeness[neighbour_id])
                neighbours += 1
            # The rest are less similar than these: they can't make the list.
            if neighbours >= limit:
                break

    # Best first; sorting is stable, so videos without a similarity keep their order.
    ranked = sorted(
        found.values(),
        key=lambda video: (video.similarity is None, -(video.similarity or 0.0)),
    )
    return ranked[:limit]


def _video(row: Row[Any], reason: str, similarity: float | None) -> SimilarVideo:
    return SimilarVideo(
        video_id=row.video_id,
        title=row.title,
        duration_seconds=row.duration_seconds,
        published_at=row.published_at,
        thumbnail_url=row.thumbnail_url,
        view_count=row.view_count,
        channel_id=row.channel_id,
        channel_title=row.channel_title,
        channel_thumbnail_url=row.channel_thumbnail_url,
        watched=False,
        reason=reason,
        similarity=similarity,
    )


def _related_video_ids(session: Session, video_id: str) -> list[str]:
    """The videos YouTube suggested next to `video_id`, newest found first."""
    rows = session.execute(
        text(
            """
            SELECT video_id FROM candidates
            WHERE source = :source AND source_detail = :video_id
            ORDER BY first_seen_at DESC, video_id
            """
        ),
        {"source": RELATED, "video_id": video_id},
    )
    return list(rows.scalars())


def _nearest(
    session: Session, embedding: Embedding, video_id: str, floor: float
) -> Iterator[list[tuple[str, float]]]:
    """Every other embedded video from `floor` similarity up, most similar first, in
    batches of (video id, cosine similarity).

    Stored vectors are scanned and sorted in SQLite (a person's library is a few thousand
    videos), so that the filters can be applied to as few batches as the list needs."""
    result = session.execute(
        text(
            """
            SELECT video_id, 1.0 - vec_distance_cosine(embedding, :embedding) AS similarity
            FROM video_embeddings WHERE video_id != :video_id
            ORDER BY similarity DESC, video_id
            """
        ),
        {"embedding": serialize_embedding(embedding), "video_id": video_id},
    )
    try:
        for rows in result.partitions(_BATCH_SIZE):
            batch = [(row.video_id, row.similarity) for row in rows if row.similarity >= floor]
            if batch:
                yield batch
            if len(batch) < len(rows):
                return  # sorted, so the rest are below the floor too
    finally:
        result.close()


@dataclass(frozen=True)
class _Rules:
    """What keeps a video off the list: the feed's hard filters and the hidden channels."""

    curation: dict[str, ChannelCuration]
    history: History
    bounds: DurationBounds
    keyword_mutes: KeywordMutes
    hidden_tags: frozenset[int]
    hidden_channels: frozenset[str]

    @classmethod
    def load(cls, session: Session, settings: Settings) -> "_Rules":
        user = get_user_settings(session, settings)
        return cls(
            curation=load_curation(session),
            history=History(
                watched=frozenset(watched_video_ids(session)),
                dismissed=frozenset(dismissed_video_ids(session)),
            ),
            bounds=DurationBounds(user.feed_min_duration_seconds, user.feed_max_duration_seconds),
            keyword_mutes=KeywordMutes(muted_keywords(session)),
            hidden_tags=frozenset(
                subscription.tag_id
                for subscription in list_tag_subscriptions(session)
                if subscription.hide
            ),
            hidden_channels=frozenset(
                hide.channel_id for hide in channel_hides.list_hides(session)
            ),
        )

    def admitted(self, session: Session, video_ids: Sequence[str]) -> dict[str, Row[Any]]:
        """The stored rows of those of `video_ids` that may be listed, in the same order."""
        if not video_ids:
            return {}
        rows = {
            row.video_id: row
            for row in session.execute(
                text(
                    """
                    SELECT v.id AS video_id, v.title, v.description, v.duration_seconds,
                           v.published_at, v.thumbnail_url, v.view_count, v.live_status,
                           v.is_short, c.id AS channel_id, c.title AS channel_title,
                           c.thumbnail_url AS channel_thumbnail_url
                    FROM videos AS v JOIN channels AS c ON c.id = v.channel_id
                    WHERE v.id IN :ids
                    """
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": list(video_ids)},
            )
        }
        tag_ids = (
            {
                id_: [tag.tag_id for tag in tags]
                for id_, tags in get_video_tags(session, rows).items()
            }
            if self.hidden_tags
            else {}
        )
        admitted: dict[str, Row[Any]] = {}
        for video_id in video_ids:
            row = rows.get(video_id)
            if row is None or row.channel_id in self.hidden_channels:
                continue
            candidate = RankCandidate(
                video_id=video_id,
                channel_id=row.channel_id,
                source=RELATED,
                title=row.title,
                description=row.description,
                duration_seconds=row.duration_seconds,
                live_status=row.live_status,
                is_short=bool(row.is_short),
            )
            reason = filter_reason(
                candidate,
                curation=self.curation,
                history=self.history,
                bounds=self.bounds,
                keyword_mutes=self.keyword_mutes,
                hidden_tags=self.hidden_tags,
                tag_ids=tag_ids.get(video_id, ()),
            )
            if reason is None:
                admitted[video_id] = row
        return admitted
