import json
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import enricher as enricher_module
from homefeed_core.candidates import SUBSCRIPTION, record
from homefeed_core.config import Settings
from homefeed_core.curation import add_topic, topic_vectors
from homefeed_core.db import open_database
from homefeed_core.embeddings import (
    Embedding,
    EmbeddingError,
    StubEmbeddingProvider,
    cosine_similarity,
    get_embedding,
)
from homefeed_core.enricher import (
    CAPTIONS_RETRY_AFTER,
    PROMPT_VERSION,
    TRANSCRIPT_SECONDS,
    Enricher,
    embedding_text,
    enrich_candidates,
    get_features,
)
from homefeed_core.gateway import ExtractionError, UnavailableError, Video
from homefeed_core.gateway.fake import FakeGateway, make_captions, make_channel, make_video
from homefeed_core.ratings import set_rating
from homefeed_core.videos import get_stored_video

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
CHANNEL = make_channel("UC" + "w" * 22, title="Woodworking", handle="@wood")
VIDEO = make_video(
    "aaaaaaaaaaa",
    channel=CHANNEL,
    title="Cutting dovetails by hand",
    description="How I cut dovetails.",
    tags=("woodworking", "dovetails"),
    duration_seconds=900,
    live_status="not_live",
    published_at=NOW - timedelta(days=30),
)
# One line every 10 seconds for 10 minutes: line i starts at 10 * i seconds.
LINES = [f"line {i}" for i in range(60)]


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


@pytest.fixture
def gateway() -> FakeGateway:
    fake = FakeGateway()
    fake.add_channel(CHANNEL, [VIDEO])
    fake.add_captions(make_captions(VIDEO.id, LINES, seconds_per_line=10))
    return fake


@pytest.fixture
def embedder() -> StubEmbeddingProvider:
    return StubEmbeddingProvider()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def enricher(
    sessions: sessionmaker[Session],
    gateway: FakeGateway,
    embedder: StubEmbeddingProvider,
    clock: Clock,
) -> Enricher:
    return Enricher(sessions, gateway, embedder, now=clock)


def video_calls(gateway: FakeGateway) -> list[str]:
    return [operation for operation, _ in gateway.calls]


def test_enrich_computes_and_stores_features(
    enricher: Enricher, sessions: sessionmaker[Session], embedder: StubEmbeddingProvider
) -> None:
    features = enricher.enrich(VIDEO.id)

    assert features.video_id == VIDEO.id
    assert (features.title, features.channel_id) == (VIDEO.title, CHANNEL.id)
    assert features.duration_seconds == 900
    assert features.tags == ("woodworking", "dovetails")
    # The first five minutes of captions: lines starting before 300 s.
    assert features.transcript_excerpt == " ".join(LINES[: TRANSCRIPT_SECONDS // 10])
    assert (features.transcript_language, features.transcript_status) == ("en", "ok")
    assert (features.embedding_model, features.prompt_version) == (embedder.model, PROMPT_VERSION)
    assert features.enriched_at == "2026-10-12T06:00:00.000Z"
    [[embedded]] = embedder.calls
    assert embedded.startswith("Cutting dovetails by hand\n\nTags: woodworking, dovetails")
    assert "How I cut dovetails." in embedded and "line 29" in embedded
    assert "line 30" not in embedded
    assert features.embedding == pytest.approx(embedder.embed([embedded])[0], abs=1e-6)

    with sessions() as session:
        assert get_features(session, VIDEO.id) == features
        stored = get_stored_video(session, VIDEO.id)
        row = session.execute(
            text("SELECT tags, embedding_model, prompt_version FROM video_features")
        ).one()
    # Metadata lands in `videos`, where the ranker's filters read it.
    assert stored is not None and stored.duration_seconds == 900
    assert (json.loads(row[0]), row[1], row[2]) == (
        ["woodworking", "dovetails"],
        "stub-embedding-v1",
        PROMPT_VERSION,
    )


def test_cache_hits_skip_work(
    enricher: Enricher, gateway: FakeGateway, embedder: StubEmbeddingProvider, clock: Clock
) -> None:
    first = enricher.enrich(VIDEO.id)
    gateway.calls.clear()
    clock.now += timedelta(days=90)

    second = enricher.enrich(VIDEO.id)
    report = enricher.enrich_many([VIDEO.id])

    assert second == first
    assert gateway.calls == []
    assert len(embedder.calls) == 1
    assert (report.enriched, report.cached, report.failed) == ([], [VIDEO.id], {})


def test_embedding_model_change_recomputes(
    sessions: sessionmaker[Session], gateway: FakeGateway, clock: Clock
) -> None:
    old = Enricher(sessions, gateway, StubEmbeddingProvider("model-a"), now=clock).enrich(VIDEO.id)
    newer = StubEmbeddingProvider("model-b", vectors={})
    clock.now += timedelta(hours=1)

    features = Enricher(sessions, gateway, newer, now=clock).enrich(VIDEO.id)

    assert features.embedding_model == "model-b"
    assert features.enriched_at > old.enriched_at
    assert len(newer.calls) == 1
    with sessions() as session:
        assert get_features(session, VIDEO.id) == features


def test_prompt_version_change_recomputes(
    enricher: Enricher,
    gateway: FakeGateway,
    embedder: StubEmbeddingProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enricher.enrich(VIDEO.id)
    monkeypatch.setattr(enricher_module, "PROMPT_VERSION", PROMPT_VERSION + 1)

    features = enricher.enrich(VIDEO.id)

    assert features.prompt_version == PROMPT_VERSION + 1
    assert len(embedder.calls) == 2
    assert video_calls(gateway).count("get_video") == 2


def test_missing_captions_still_enrich_from_metadata(
    enricher: Enricher, gateway: FakeGateway, embedder: StubEmbeddingProvider
) -> None:
    other = make_video("bbbbbbbbbbb", channel=CHANNEL, title="No captions here", description="")
    gateway.add_video(other)

    features = enricher.enrich(other.id)

    assert features.transcript_excerpt is None
    assert (features.transcript_language, features.transcript_status) == (None, "missing")
    assert embedder.calls == [["No captions here"]]
    assert len(features.embedding) == embedder.dimensions


def test_empty_captions_count_as_missing(enricher: Enricher, gateway: FakeGateway) -> None:
    gateway.add_captions(make_captions(VIDEO.id, [], language="en-orig", is_automatic=True))

    features = enricher.enrich(VIDEO.id)

    assert (features.transcript_excerpt, features.transcript_status) == (None, "missing")
    assert features.transcript_language == "en-orig"


def test_missing_captions_of_a_new_upload_are_looked_for_again_once(
    enricher: Enricher, gateway: FakeGateway, clock: Clock
) -> None:
    fresh = make_video("ccccccccccc", channel=CHANNEL, published_at=NOW - timedelta(hours=2))
    gateway.add_video(fresh)
    assert enricher.enrich(fresh.id).transcript_status == "missing"

    clock.now += CAPTIONS_RETRY_AFTER / 2
    enricher.enrich(fresh.id)
    assert video_calls(gateway).count("get_captions") == 1  # too early to look again

    gateway.add_captions(make_captions(fresh.id, ["Automatic captions arrived."]))
    clock.now = NOW + CAPTIONS_RETRY_AFTER
    features = enricher.enrich(fresh.id)
    assert features.transcript_excerpt == "Automatic captions arrived."

    # Once captions are found (or a day after upload) the features stay.
    clock.now += CAPTIONS_RETRY_AFTER * 5
    enricher.enrich(fresh.id)
    assert video_calls(gateway).count("get_captions") == 2


def test_missing_captions_of_an_old_video_are_not_looked_for_again(
    enricher: Enricher, gateway: FakeGateway, clock: Clock
) -> None:
    old = make_video("ccccccccccc", channel=CHANNEL, published_at=NOW - timedelta(days=3))
    gateway.add_video(old)
    enricher.enrich(old.id)

    clock.now += CAPTIONS_RETRY_AFTER * 5
    enricher.enrich(old.id)

    assert video_calls(gateway).count("get_captions") == 1


def test_failed_caption_fetch_is_retried_a_day_later(
    enricher: Enricher, gateway: FakeGateway, clock: Clock
) -> None:
    gateway.fail("get_captions", VIDEO.id, ExtractionError("timed out"))

    features = enricher.enrich(VIDEO.id)
    assert (features.transcript_excerpt, features.transcript_status) == (None, "failed")
    assert enricher.enrich(VIDEO.id) == features  # cached for now

    del gateway.failures[("get_captions", VIDEO.id)]
    clock.now += CAPTIONS_RETRY_AFTER
    assert enricher.enrich(VIDEO.id).transcript_status == "ok"


def test_unavailable_video_raises_and_stores_nothing(
    enricher: Enricher, sessions: sessionmaker[Session], embedder: StubEmbeddingProvider
) -> None:
    with pytest.raises(UnavailableError):
        enricher.enrich("zzzzzzzzzzz")

    assert embedder.calls == []
    with sessions() as session:
        assert get_features(session, "zzzzzzzzzzz") is None
        assert get_embedding(session, "zzzzzzzzzzz") is None


def test_enrich_many_reports_failures_and_carries_on(enricher: Enricher) -> None:
    enricher.enrich(VIDEO.id)
    report = enricher.enrich_many(["zzzzzzzzzzz", VIDEO.id, "zzzzzzzzzzz"])

    assert report.enriched == []
    assert report.cached == [VIDEO.id]
    assert list(report.failed) == ["zzzzzzzzzzz"]
    assert "unavailable" in report.failed["zzzzzzzzzzz"]


def test_similar_texts_get_their_embeddings(
    sessions: sessionmaker[Session], gateway: FakeGateway, clock: Clock
) -> None:
    """The stored embedding is the provider's vector for the video's text."""
    other = make_video("bbbbbbbbbbb", channel=CHANNEL, title="Other")
    gateway.add_video(other)
    embedder = StubEmbeddingProvider(vectors={"Other": [1.0] + [0.0] * 383})

    features = Enricher(sessions, gateway, embedder, now=clock).enrich(other.id)

    assert cosine_similarity(features.embedding, [1.0] + [0.0] * 383) == pytest.approx(1.0)


def test_enrich_candidates_enriches_the_feed_window(
    enricher: Enricher, sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    recent = make_video("bbbbbbbbbbb", channel=CHANNEL)
    stale = make_video("ccccccccccc", channel=CHANNEL)
    gateway.add_video(recent)
    gateway.add_video(stale)
    with sessions.begin() as session:
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, 'Woodworking')"), {"id": CHANNEL.id}
        )
        for video, seen in [
            (VIDEO, NOW - timedelta(days=1)),
            (recent, NOW - timedelta(hours=1)),
            (stale, NOW - timedelta(days=30)),
        ]:
            session.execute(
                text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :channel, 'RSS')"),
                {"id": video.id, "channel": CHANNEL.id},
            )
            record(session, [video.id], source=SUBSCRIPTION, now=seen)
    enricher.enrich(VIDEO.id)

    report = enrich_candidates(
        enricher=enricher, sessions=sessions, settings=Settings(feed_candidate_days=7), now=NOW
    )

    assert report.enriched == [recent.id]
    assert report.cached == [VIDEO.id]
    with sessions() as session:
        assert get_features(session, stale.id) is None
        features = get_features(session, recent.id)
    assert features is not None and features.title == recent.title  # RSS title replaced


def test_enrich_candidates_also_enriches_top_and_bottom_tier_rated_videos(
    enricher: Enricher, gateway: FakeGateway, sessions: sessionmaker[Session]
) -> None:
    # Rated videos that never were candidates (e.g. opened from a pasted URL).
    loved, hated, middling = (
        make_video(video_id, channel=CHANNEL)
        for video_id in ("ddddddddddd", "eeeeeeeeeee", "fffffffffff")
    )
    with sessions.begin() as session:
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, 'Woodworking')"), {"id": CHANNEL.id}
        )
        rated: list[tuple[Video, float]] = [(loved, 7.2), (hated, 3.8), (middling, 4.7)]
        for video, score in rated:
            gateway.add_video(video)
            session.execute(
                text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :channel, 'T')"),
                {"id": video.id, "channel": CHANNEL.id},
            )
            set_rating(session, video.id, score)

    report = enrich_candidates(enricher=enricher, sessions=sessions, now=NOW)

    assert report.enriched == [loved.id, hated.id]
    with sessions() as session:
        assert get_features(session, middling.id) is None


def test_enrich_candidates_re_embeds_topics_from_another_model(
    enricher: Enricher, sessions: sessionmaker[Session], embedder: StubEmbeddingProvider
) -> None:
    old = StubEmbeddingProvider("old-model", vectors={"woodworking": [1.0] + [0.0] * 383})
    with sessions.begin() as session:
        add_topic(session, old, name="Wood", description="woodworking", weight=1)

    enrich_candidates(enricher=enricher, sessions=sessions, settings=Settings(), now=NOW)
    enrich_candidates(enricher=enricher, sessions=sessions, settings=Settings(), now=NOW)

    assert embedder.calls == [["woodworking"]]
    with sessions() as session:
        [vector] = topic_vectors(session)
        model = session.execute(text("SELECT embedding_model FROM topics")).scalar_one()
    assert model == embedder.model
    assert vector.embedding == pytest.approx(embedder.embed(["woodworking"])[0], abs=1e-6)


SECOND = make_video(
    "bbbbbbbbbbb", channel=CHANNEL, title="Sharpening chisels", published_at=NOW - timedelta(days=2)
)


class FailingEmbedder(StubEmbeddingProvider):
    """Embeds `ok_calls` calls, then fails like an unreachable API."""

    def __init__(self, model: str, *, ok_calls: int) -> None:
        super().__init__(model)
        self.ok_calls = ok_calls

    def embed(self, texts: Sequence[str]) -> list[Embedding]:
        if len(self.calls) >= self.ok_calls:
            self.calls.append(list(texts))
            raise EmbeddingError("Can't reach the API")
        return super().embed(texts)


def enrich_with(
    sessions: sessionmaker[Session], gateway: FakeGateway, model: str, clock: Clock
) -> None:
    Enricher(sessions, gateway, StubEmbeddingProvider(model), now=clock).enrich_many(
        [VIDEO.id, SECOND.id]
    )


def test_a_model_change_re_embeds_stored_videos_without_youtube(
    sessions: sessionmaker[Session], gateway: FakeGateway, clock: Clock
) -> None:
    gateway.add_channel(CHANNEL, [VIDEO, SECOND])
    enrich_with(sessions, gateway, "model-a", clock)
    with sessions() as session:
        before = get_features(session, VIDEO.id)
    gateway.calls.clear()
    newer = StubEmbeddingProvider("model-b")
    enricher = Enricher(sessions, gateway, newer, now=clock)

    assert sorted(enricher.refresh_video_embeddings()) == [VIDEO.id, SECOND.id]

    assert gateway.calls == []
    assert before is not None
    with sessions() as session:
        after = get_features(session, VIDEO.id)
    # Same text as enrichment embedded, the features stay as they were.
    assert after is not None and after.embedding_model == "model-b"
    assert after.embedding == pytest.approx(
        newer.embed([embedding_text(VIDEO, before.transcript_excerpt)])[0], abs=1e-6
    )
    assert (after.enriched_at, after.transcript_excerpt) == (
        before.enriched_at,
        before.transcript_excerpt,
    )
    # Now current: nothing to re-embed, and enrichment is a cache hit.
    assert enricher.refresh_video_embeddings() == []
    assert enricher.enrich_many([VIDEO.id]).cached == [VIDEO.id]
    assert gateway.calls == []


def test_a_failed_re_embedding_leaves_no_vectors_of_the_old_model(
    sessions: sessionmaker[Session],
    gateway: FakeGateway,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway.add_channel(CHANNEL, [VIDEO, SECOND])
    enrich_with(sessions, gateway, "model-a", clock)
    monkeypatch.setattr(enricher_module, "REFRESH_BATCH_SIZE", 1)
    failing = FailingEmbedder("model-b", ok_calls=1)
    enricher = Enricher(sessions, gateway, failing, now=clock)

    with pytest.raises(EmbeddingError):
        enricher.refresh_video_embeddings()

    with sessions() as session:
        models = dict(
            session.execute(text("SELECT video_id, embedding_model FROM video_features")).all()
        )
        embedded = {video_id for video_id in models if get_embedding(session, video_id) is not None}
    # One batch got through; the other video has no vector rather than model-a's.
    assert embedded == {video_id for video_id, model in models.items() if model == "model-b"}
    assert len(embedded) == 1

    # enrich_candidates logs the failure and goes on; the next run finishes the job.
    report = enrich_candidates(enricher=enricher, sessions=sessions, settings=Settings(), now=NOW)
    assert report.reembedded == []
    failing.ok_calls = 100
    report = enrich_candidates(enricher=enricher, sessions=sessions, settings=Settings(), now=NOW)
    assert len(report.reembedded) == 1
    with sessions() as session:
        assert all(get_embedding(session, v) is not None for v in (VIDEO.id, SECOND.id))


def test_enrich_many_records_embedding_failures(
    sessions: sessionmaker[Session], gateway: FakeGateway, clock: Clock
) -> None:
    enricher = Enricher(sessions, gateway, FailingEmbedder("model-b", ok_calls=0), now=clock)

    report = enricher.enrich_many([VIDEO.id])

    assert list(report.failed) == [VIDEO.id]
    with sessions() as session:
        assert get_features(session, VIDEO.id) is None
