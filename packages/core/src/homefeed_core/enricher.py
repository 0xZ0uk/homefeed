"""Content features for videos: metadata, a transcript excerpt and an embedding.

`Enricher.enrich(video_id)` fetches the video's metadata and captions through the
Gateway, stores the metadata in `videos` (so the ranker's filters see durations and
live status), keeps the first `TRANSCRIPT_SECONDS` of captions as an excerpt, and embeds
title, tags, description and excerpt. Features go to `video_features` and the embedding
to the sqlite-vec table `video_embeddings` (read it with `homefeed_core.embeddings`).

Features are computed once and reused while they match the current embedding model and
`PROMPT_VERSION`; bump `PROMPT_VERSION` whenever `embedding_text` or the excerpt changes
so every video is recomputed on its next enrichment. A video without captions still
gets features (from its metadata alone). Missing captions are looked for again once,
`CAPTIONS_RETRY_AFTER` later, for videos enriched soon after upload (YouTube adds
automatic captions some time after publishing), and failed caption fetches are retried
after the same delay.

The worker calls `enrich_candidates` before ranking. It also enriches the videos rated
top or bottom tier, which the ranker's similarity features compare candidates with:
a video can be rated without ever being a candidate (e.g. opened from a pasted URL).

After an `EMBEDDING_MODEL` change, `enrich_candidates` first re-embeds every stored video
from its stored text (`refresh_video_embeddings`, no YouTube requests), then topic
descriptions and tag labels, so all similarities compare vectors of one model. Stale
vectors are dropped before re-embedding, so if the embedding API fails partway the
videos left go without an embedding (and are tried again next run) rather than mixing
two models' vectors. An embedding failure never fails the run: videos that couldn't be
embedded are recorded as failed and tried again next time.

With an LLM provider configured (see homefeed_core.llm_tags), `enrich_candidates` then
tags the same videos and every rated video (training uses their tags too) with topic,
depth, clickbait and rage-bait, and specific tags (homefeed_core.tags). Tagging never
fails the run: errors are logged and the untagged videos are tried again next time.
"""

import argparse
import json
import logging
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Literal, cast

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import curation
from homefeed_core.candidates import list_candidates
from homefeed_core.config import Settings, get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.embeddings import (
    Embedding,
    EmbeddingError,
    EmbeddingProvider,
    get_embedding,
    get_embedding_provider,
    store_embedding,
)
from homefeed_core.gateway import Gateway, GatewayError, Video, create_gateway
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.llm_tags import Tagger, TagReport, get_tagger
from homefeed_core.progress import Phases, Progress, ProgressLine, configure_cli_logging
from homefeed_core.ratings import list_ratings, tier_rated_video_ids
from homefeed_core.tags import refresh_tag_embeddings
from homefeed_core.videos import store_video

logger = logging.getLogger(__name__)

# Version of how the embedded text is built (excerpt length, template). Bump on change.
PROMPT_VERSION = 1
# How much of the captions goes into the transcript excerpt.
TRANSCRIPT_SECONDS = 5 * 60
# Descriptions are mostly links and sponsor copy after the first paragraphs.
DESCRIPTION_CHARS = 1000
CAPTIONS_RETRY_AFTER = timedelta(days=1)

TranscriptStatus = Literal["ok", "missing", "failed"]
# Videos re-embedded per batch (and per transaction) after a model change.
REFRESH_BATCH_SIZE = 64


@dataclass(frozen=True)
class VideoFeatures:
    video_id: str
    title: str
    channel_id: str
    description: str | None
    duration_seconds: int | None
    published_at: str | None  # ISO 8601 UTC
    tags: tuple[str, ...]  # the uploader's YouTube tags
    transcript_excerpt: str | None  # first ~5 minutes of captions; None without captions
    transcript_language: str | None  # caption track language, e.g. "en" or "en-orig"
    transcript_status: TranscriptStatus
    embedding: Embedding  # unit length
    embedding_model: str
    prompt_version: int
    enriched_at: str  # ISO 8601 UTC


@dataclass(frozen=True)
class EnrichReport:
    enriched: list[str] = field(default_factory=list[str])  # computed in this run
    cached: list[str] = field(default_factory=list[str])  # already up to date
    failed: dict[str, str] = field(default_factory=dict[str, str])  # video id -> error
    # Stored videos re-embedded after an embedding model change (see `enrich_candidates`).
    reembedded: list[str] = field(default_factory=list[str])
    # LLM tagging after enrichment (see `enrich_candidates`); None when it didn't run.
    tags: TagReport | None = None


class Enricher:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        gateway: Gateway,
        embedder: EmbeddingProvider,
        *,
        tagger: Tagger | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._gateway = gateway
        self._embedder = embedder
        self._tagger = tagger
        self._now = now

    def enrich(self, video_id: str) -> VideoFeatures:
        """The video's features, computed now unless up-to-date ones are stored.

        Raises `GatewayError` when the video's metadata can't be fetched (nothing is
        stored then). Caption failures don't raise: the features go without a transcript.
        """
        cached = self._cached(video_id)
        if cached is not None:
            return cached
        return self._compute(video_id)

    def enrich_many(
        self, video_ids: Iterable[str], *, progress: Progress | None = None
    ) -> EnrichReport:
        """Enrich each video, recording failures instead of raising them. `progress` gets
        (done, to do) over the videos that aren't up to date, after each one."""
        report = EnrichReport()
        todo: list[str] = []
        for video_id in dict.fromkeys(video_ids):
            if self._cached(video_id) is not None:
                report.cached.append(video_id)
            else:
                todo.append(video_id)
        for done, video_id in enumerate(todo, start=1):
            try:
                self._compute(video_id)
            except (GatewayError, EmbeddingError) as error:
                logger.warning("Could not enrich %s: %s", video_id, error)
                report.failed[video_id] = str(error)
            else:
                report.enriched.append(video_id)
            if progress is not None:
                progress(done, len(todo))
        return report

    def tag_many(
        self, video_ids: Iterable[str], *, progress: Progress | None = None
    ) -> TagReport | None:
        """LLM-tag the videos without current tags; None without a tagger. Never raises:
        a failure is logged and the videos are left for the next run."""
        if self._tagger is None:
            return None
        try:
            return self._tagger.tag_many(video_ids, progress=progress)
        except Exception:
            logger.exception("LLM tagging failed; continuing without new tags")
            return None

    @property
    def embedding_model(self) -> str:
        return self._embedder.model

    def refresh_video_embeddings(self, *, progress: Progress | None = None) -> list[str]:
        """Re-embed the stored videos embedded by another model than the current one,
        from their stored text (no YouTube requests), newest enrichment first. Returns
        their ids. Raises EmbeddingError if the embedder fails; the videos not done by
        then are left without an embedding (see the module docstring)."""
        model = self._embedder.model
        with self._sessions.begin() as session:
            rows = session.execute(
                text(
                    """
                    SELECT v.id, v.title, v.description, f.tags, f.transcript_excerpt
                    FROM video_features AS f JOIN videos AS v ON v.id = f.video_id
                    WHERE f.embedding_model != :model
                    ORDER BY f.enriched_at DESC, v.id
                    """
                ),
                {"model": model},
            ).all()
            if not rows:
                return []
            logger.info("Re-embedding %d videos with %s", len(rows), model)
            # No vectors of two models side by side, even if re-embedding stops partway.
            session.execute(
                text(
                    """
                    DELETE FROM video_embeddings WHERE video_id IN (
                        SELECT video_id FROM video_features WHERE embedding_model != :model
                    )
                    """
                ),
                {"model": model},
            )
        done: list[str] = []
        for start in range(0, len(rows), REFRESH_BATCH_SIZE):
            batch = rows[start : start + REFRESH_BATCH_SIZE]
            texts = [
                embedding_text(StoredText(title, tuple(json.loads(tags)), description), excerpt)
                for _, title, description, tags, excerpt in batch
            ]
            vectors = self._embedder.embed(texts)
            with self._sessions.begin() as session:
                for (video_id, *_), vector in zip(batch, vectors, strict=True):
                    store_embedding(session, video_id, vector)
                    session.execute(
                        text(
                            "UPDATE video_features SET embedding_model = :model "
                            "WHERE video_id = :id"
                        ),
                        {"model": model, "id": video_id},
                    )
                    done.append(video_id)
            if progress is not None:
                progress(len(done), len(rows))
        logger.info("Re-embedded %d videos with %s", len(done), model)
        return done

    def refresh_topic_embeddings(self) -> list[int]:
        """Re-embed topics embedded by another model. Returns their ids."""
        with self._sessions.begin() as session:
            refreshed = curation.refresh_topic_embeddings(session, self._embedder)
        if refreshed:
            logger.info("Re-embedded %d topics with %s", len(refreshed), self._embedder.model)
        return refreshed

    def refresh_tag_embeddings(self) -> list[int]:
        """Embed tags without an embedding from the current model (new ones, and all after
        an `EMBEDDING_MODEL` change). Returns their ids."""
        with self._sessions.begin() as session:
            refreshed = refresh_tag_embeddings(session, self._embedder)
        if refreshed:
            logger.info("Embedded %d tags with %s", len(refreshed), self._embedder.model)
        return refreshed

    def is_current(self, features: VideoFeatures) -> bool:
        """Whether stored `features` can be reused rather than recomputed."""
        if (features.embedding_model, features.prompt_version) != (
            self._embedder.model,
            PROMPT_VERSION,
        ):
            return False
        if features.transcript_status == "ok":
            return True
        enriched_at = _parse_timestamp(features.enriched_at)
        if self._now() - enriched_at < CAPTIONS_RETRY_AFTER:
            return True
        if features.transcript_status == "failed":
            return False
        # Missing captions: look again if the video was new when it was enriched.
        published_at = _parse_timestamp(features.published_at) if features.published_at else None
        return published_at is None or enriched_at - published_at >= CAPTIONS_RETRY_AFTER

    def _cached(self, video_id: str) -> VideoFeatures | None:
        with self._sessions() as session:
            features = get_features(session, video_id)
        return features if features is not None and self.is_current(features) else None

    def _compute(self, video_id: str) -> VideoFeatures:
        video = self._gateway.get_video(video_id)
        excerpt, language, status = self._transcript(video_id)
        [embedding] = self._embedder.embed([embedding_text(video, excerpt)])
        with self._sessions.begin() as session:
            store_video(session, video)
            session.execute(
                text(
                    """
                    INSERT INTO video_features (video_id, tags, transcript_excerpt,
                        transcript_language, transcript_status, embedding_model,
                        prompt_version, enriched_at)
                    VALUES (:video_id, :tags, :excerpt, :language, :status, :model,
                            :prompt_version, :enriched_at)
                    ON CONFLICT (video_id) DO UPDATE SET
                        tags = excluded.tags,
                        transcript_excerpt = excluded.transcript_excerpt,
                        transcript_language = excluded.transcript_language,
                        transcript_status = excluded.transcript_status,
                        embedding_model = excluded.embedding_model,
                        prompt_version = excluded.prompt_version,
                        enriched_at = excluded.enriched_at
                    """
                ),
                {
                    "video_id": video_id,
                    "tags": json.dumps(list(video.tags)),
                    "excerpt": excerpt,
                    "language": language,
                    "status": status,
                    "model": self._embedder.model,
                    "prompt_version": PROMPT_VERSION,
                    "enriched_at": format_timestamp(self._now()),
                },
            )
            store_embedding(session, video_id, embedding)
            features = get_features(session, video_id)
        assert features is not None
        return features

    def _transcript(self, video_id: str) -> tuple[str | None, str | None, TranscriptStatus]:
        """(excerpt, caption language, status) for the video's captions."""
        try:
            captions = self._gateway.get_captions(video_id)
        except GatewayError as error:
            logger.warning("Could not fetch captions for %s: %s", video_id, error)
            return None, None, "failed"
        if captions is None:
            return None, None, "missing"
        excerpt = captions.text(until_seconds=TRANSCRIPT_SECONDS)
        if not excerpt:
            return None, captions.language, "missing"
        return excerpt, captions.language, "ok"


@dataclass(frozen=True)
class StoredText:
    """What `embedding_text` reads of a video, as stored (for re-embedding)."""

    title: str
    tags: Sequence[str]
    description: str | None


def embedding_text(video: Video | StoredText, transcript_excerpt: str | None) -> str:
    """The text embedded for a video. Bump `PROMPT_VERSION` when changing it.

    Most important first, since models truncate long inputs (512 tokens for bge-small,
    32k for pplx-embed).
    """
    parts = [video.title]
    if video.tags:
        parts.append("Tags: " + ", ".join(video.tags))
    if video.description:
        parts.append(video.description[:DESCRIPTION_CHARS].strip())
    if transcript_excerpt:
        parts.append(transcript_excerpt)
    return "\n\n".join(part for part in parts if part)


def get_features(session: Session, video_id: str) -> VideoFeatures | None:
    """The stored features of `video_id` (current or not), or None if never enriched."""
    row = session.execute(
        text(
            """
            SELECT v.id, v.title, v.channel_id, v.description, v.duration_seconds,
                   v.published_at, f.tags, f.transcript_excerpt, f.transcript_language,
                   f.transcript_status, f.embedding_model, f.prompt_version, f.enriched_at
            FROM video_features AS f JOIN videos AS v ON v.id = f.video_id
            WHERE f.video_id = :id
            """
        ),
        {"id": video_id},
    ).one_or_none()
    if row is None:
        return None
    embedding = get_embedding(session, video_id)
    if embedding is None:
        return None
    (
        _,
        title,
        channel_id,
        description,
        duration,
        published_at,
        tags,
        excerpt,
        language,
        status,
        model,
        prompt_version,
        enriched_at,
    ) = row
    return VideoFeatures(
        video_id=video_id,
        title=title,
        channel_id=channel_id,
        description=description,
        duration_seconds=duration,
        published_at=published_at,
        tags=tuple(json.loads(tags)),
        transcript_excerpt=excerpt,
        transcript_language=language,
        transcript_status=cast(TranscriptStatus, status),
        embedding=embedding,
        embedding_model=model,
        prompt_version=prompt_version,
        enriched_at=enriched_at,
    )


@lru_cache
def get_enricher() -> Enricher:
    """The process-wide production enricher (one embedding model per process), tagging
    with the configured LLM provider, if any."""
    sessions = get_session_factory()
    return Enricher(
        sessions, create_gateway(sessions), get_embedding_provider(), tagger=get_tagger()
    )


def enrich_candidates(
    *,
    enricher: Enricher | None = None,
    sessions: sessionmaker[Session] | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
    progress: Phases | None = None,
) -> EnrichReport:
    """Enrich the candidates the next feed will rank (first seen within
    `FEED_CANDIDATE_DAYS`), newest first, then the top-tier and bottom-tier rated videos
    the ranker compares them with. Up-to-date ones are skipped. Stored videos, topics and
    tags embedded by another model are re-embedded first (a failure there is logged and
    retried next run). Then, if the enricher has a tagger, those videos and every other
    rated video are LLM-tagged (`EnrichReport.tags`). `progress` makes a `Progress` per
    phase ("Re-embedding", "Enriching", "Tagging"; see homefeed_core.progress)."""
    enricher = enricher or get_enricher()

    def phase(label: str) -> Progress | None:
        return None if progress is None else progress(label)

    reembedded: list[str] = []
    try:
        reembedded = enricher.refresh_video_embeddings(progress=phase("Re-embedding"))
        enricher.refresh_topic_embeddings()
        enricher.refresh_tag_embeddings()
    except EmbeddingError as error:
        logger.warning("Re-embedding stopped; trying again next run: %s", error)
    sessions = sessions or get_session_factory()
    settings = settings or get_settings()
    since = (now or datetime.now(UTC)) - timedelta(days=settings.feed_candidate_days)
    with sessions() as session:
        video_ids = [candidate.video_id for candidate in list_candidates(session, since=since)]
        video_ids += tier_rated_video_ids(session)
        rated_ids = [rating.video_id for rating in list_ratings(session)]
    report = enricher.enrich_many(video_ids, progress=phase("Enriching"))
    tags = enricher.tag_many([*video_ids, *rated_ids], progress=phase("Tagging"))
    return replace(report, reembedded=reembedded, tags=tags)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the worker's enrichment once, now: `uv run python -m homefeed_core.enricher`
    (re-embeds after an `EMBEDDING_MODEL` change, enriches the next feed's candidates and
    tags them). With `--reembed`, only re-embeds stored videos, topics and tags made with
    another embedding model."""
    parser = argparse.ArgumentParser(
        prog="python -m homefeed_core.enricher", description=main.__doc__
    )
    parser.add_argument(
        "--reembed",
        action="store_true",
        help="only re-embed what another embedding model made (no YouTube, no tagging)",
    )
    args = parser.parse_args(argv)
    line = ProgressLine()
    configure_cli_logging(line)
    if args.reembed:
        return _reembed(get_enricher(), line)
    report = enrich_candidates(progress=line.phase)
    line.clear()
    print(
        f"Enrichment: {len(report.enriched)} enriched, {len(report.cached)} already up to "
        f"date, {len(report.failed)} failed (tried again next run)"
        + (f"; {len(report.reembedded)} re-embedded" if report.reembedded else "")
    )
    tags = report.tags
    if tags is None:
        print("Tagging: off (see LLM_PROVIDER)")
    else:
        print(
            f"Tagging: {len(tags.tagged)} tagged, {len(tags.cached)} already tagged, "
            f"{len(tags.failed)} failed (tried again next run)"
            + (f", {len(tags.skipped)} left for the next run" if tags.skipped else "")
            + (f"; stopped: {tags.stopped}" if tags.stopped else "")
        )
    return 0


def _reembed(enricher: Enricher, line: ProgressLine) -> int:
    model = enricher.embedding_model
    try:
        videos = enricher.refresh_video_embeddings(progress=line.phase("Re-embedding"))
        topics = enricher.refresh_topic_embeddings()
        tags = enricher.refresh_tag_embeddings()
    except EmbeddingError as error:
        line.clear()
        print(f"Re-embedding stopped (run it again to carry on): {error}")
        return 1
    line.clear()
    if not (videos or topics or tags):
        print(f"Nothing to re-embed: everything already uses {model}")
    else:
        print(
            f"Re-embedded with {model}: {len(videos)} videos, {len(topics)} topics, "
            f"{len(tags)} tags"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
