"""Text embeddings: the provider interface and the stored video embeddings.

Providers turn texts into unit-length vectors of 384 floats. `EMBEDDING_PROVIDER`
picks the production one (`get_embedding_provider`): `FastEmbedProvider` runs a
fastembed (ONNX Runtime) model in the process (`BAAI/bge-small-en-v1.5` by default,
loaded on first use), `OpenRouterEmbeddingProvider` calls OpenRouter's embeddings API
(e.g. `perplexity/pplx-embed-v1-0.6b`, asking for 384 dimensions). Tests use
`StubEmbeddingProvider`, which needs no model. A provider's `model` names what produced a
vector and is stored with it, so changing it recomputes (see
`Enricher.refresh_video_embeddings`).

Models disagree on what a similarity means (bge-small rates unrelated videos about 0.6,
pplx-embed about 0.25), so the thresholds that read similarities come per model:
`calibration(settings)` (see `CALIBRATIONS`).

Video embeddings live in the sqlite-vec table `video_embeddings`; the enricher writes
them, and anything ranking by similarity reads them:

    with sessions() as session:
        vectors = get_embeddings(session, video_ids)  # {video_id: Embedding}
    cosine_similarity(vectors[a], vectors[b])
"""

import hashlib
import json
import logging
import math
import random
import struct
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from homefeed_core.config import OPENROUTER_BASE_URL, Settings, get_settings

if TYPE_CHECKING:
    from fastembed import TextEmbedding

logger = logging.getLogger(__name__)

# Dimension of the `video_embeddings` table (bge-small's; API models are asked for it).
EMBEDDING_DIMENSIONS = 384
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
# Shown for requests in the OpenRouter dashboard (its optional app attribution header).
OPENROUTER_APP_TITLE = "Homefeed"


class EmbeddingError(Exception):
    """Texts couldn't be embedded (the API is unreachable, refuses, or answers badly)."""


type Embedding = tuple[float, ...]


class EmbeddingProvider(Protocol):
    """Embeds texts as unit-length vectors of `dimensions` floats."""

    # Identifies the model (and anything else that changes its output); stored with
    # each embedding so a change triggers recomputation.
    model: str
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[Embedding]:
        """One embedding per text, in order."""
        ...


class FastEmbedProvider:
    """A fastembed (ONNX Runtime) model, downloaded into `cache_dir` and loaded on first use.

    Loading takes a few seconds and ~150 MB of memory, so keep one instance per process.
    Thread-safe.
    """

    def __init__(
        self,
        model: str = DEFAULT_EMBEDDING_MODEL,
        *,
        dimensions: int = EMBEDDING_DIMENSIONS,
        cache_dir: Path | None = None,
        batch_size: int = 32,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._cache_dir = cache_dir
        self._batch_size = batch_size
        self._loaded: TextEmbedding | None = None
        self._lock = threading.Lock()

    def embed(self, texts: Sequence[str]) -> list[Embedding]:
        if not texts:
            return []
        with self._lock:
            vectors = list(self._load().embed(list(texts), batch_size=self._batch_size))
        # fastembed's models answer unit vectors already; normalizing guards the ones that don't.
        return [normalize([float(x) for x in vector]) for vector in vectors]

    def _load(self) -> "TextEmbedding":
        if self._loaded is None:
            # Imported here: onnxruntime takes a moment to import and most processes never embed.
            from fastembed import TextEmbedding

            dimensions = TextEmbedding.get_embedding_size(self.model)
            if dimensions != self.dimensions:
                raise ValueError(
                    f"{self.model} makes {dimensions}-dimensional embeddings, "
                    f"expected {self.dimensions}"
                )
            self._loaded = TextEmbedding(
                self.model, cache_dir=str(self._cache_dir) if self._cache_dir else None
            )
        return self._loaded


# Posts a JSON body (url, body, headers, timeout) and returns the decoded JSON answer.
type PostJson = Callable[[str, Mapping[str, Any], Mapping[str, str], float], Any]


def post_json(url: str, body: Mapping[str, Any], headers: Mapping[str, str], timeout: float) -> Any:
    """POST `body` as JSON; the decoded answer. Raises `EmbeddingError` on any failure."""
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read()[:500].decode(errors="replace")
        raise EmbeddingError(f"HTTP {error.code} from {url}: {detail}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise EmbeddingError(f"Can't reach {url}: {error}") from error
    except json.JSONDecodeError as error:
        raise EmbeddingError(f"Non-JSON answer from {url}: {error}") from error


class OpenRouterEmbeddingProvider:
    """OpenRouter's embeddings API (`POST {base_url}/embeddings`, OpenAI-compatible) with a
    bearer key. Asks for `dimensions` floats, so the model must support shortening its
    vectors (Matryoshka models such as pplx-embed, qwen3-embedding, text-embedding-3 do);
    one that doesn't answers with another length and fails with `EmbeddingError`.
    Sends at most `batch_size` texts per request. Raises `EmbeddingError` on any failure.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        dimensions: int = EMBEDDING_DIMENSIONS,
        base_url: str = OPENROUTER_BASE_URL,
        timeout: float = 60.0,
        batch_size: int = 64,
        post: PostJson | None = None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._api_key = api_key
        self._url = f"{base_url.rstrip('/')}/embeddings"
        self._timeout = timeout
        self._batch_size = batch_size
        self._post = post or post_json

    def embed(self, texts: Sequence[str]) -> list[Embedding]:
        vectors: list[Embedding] = []
        for start in range(0, len(texts), self._batch_size):
            vectors += self._embed_batch(texts[start : start + self._batch_size])
        return vectors

    def _embed_batch(self, texts: Sequence[str]) -> list[Embedding]:
        answer = self._post(
            self._url,
            {
                "model": self.model,
                "input": list(texts),
                "dimensions": self.dimensions,
                "encoding_format": "float",
            },
            {"Authorization": f"Bearer {self._api_key}", "X-Title": OPENROUTER_APP_TITLE},
            self._timeout,
        )
        try:
            data = cast(list[dict[str, Any]], answer["data"])
            ordered = sorted(data, key=lambda item: item["index"])
            vectors = [[float(x) for x in item["embedding"]] for item in ordered]
        except (KeyError, TypeError, ValueError) as error:
            raise EmbeddingError(f"Unexpected embeddings answer: {str(answer)[:300]}") from error
        if len(vectors) != len(texts):
            raise EmbeddingError(f"Asked for {len(texts)} embeddings, got {len(vectors)}")
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise EmbeddingError(
                    f"{self.model} answered with {len(vector)} dimensions, not "
                    f"{self.dimensions}: it may not support shortening its embeddings"
                )
        try:
            return [normalize(vector) for vector in vectors]
        except ValueError as error:
            raise EmbeddingError(f"{self.model} answered with a zero vector") from error


def make_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """A provider for `EMBEDDING_PROVIDER` and `EMBEDDING_MODEL`. Raises ValueError for the
    OpenRouter provider without `OPENROUTER_API_KEY`."""
    settings = settings or get_settings()
    if settings.embedding_provider == "openrouter":
        if settings.openrouter_api_key is None:
            raise ValueError("EMBEDDING_PROVIDER=openrouter needs OPENROUTER_API_KEY")
        return OpenRouterEmbeddingProvider(
            settings.openrouter_api_key.get_secret_value(),
            model=settings.embedding_model,
            timeout=settings.embedding_timeout_seconds,
        )
    return FastEmbedProvider(settings.embedding_model, cache_dir=settings.data_dir / "models")


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    """The process-wide production provider (`make_embedding_provider`).

    Shared so a process loads a local model at most once, and only when it first embeds
    something: the worker for videos, tags and topics, the API when a topic or tag is
    saved.
    """
    return make_embedding_provider()


@dataclass(frozen=True)
class Calibration:
    """How an embedding model's cosine similarities read (see the module docstring)."""

    # Below it a candidate counts as unrelated to a rated video (ranker.similarity_score).
    similarity_floor: float
    # Below it a video counts as unrelated to a topic's description (ranker.topic_boost).
    topic_similarity_floor: float
    # From it a proposed tag merges into the most similar existing one (homefeed_core.tags).
    tag_merge_threshold: float


# Measured on the library's videos, sample topic descriptions and tag pairs (plurals and
# spelling variants should merge; "nba" / "basketball", "world war i" / "world war ii"
# should not). bge-small keeps the values it always had: its floors sit below even
# unrelated pairs (~0.6), so every topic boosts every video a little.
CALIBRATIONS: dict[str, Calibration] = {
    "BAAI/bge-small-en-v1.5": Calibration(0.3, 0.3, 0.92),
    # Unrelated videos ~0.25 (p90 0.42); a topic's matching videos 0.35-0.5, unrelated
    # ones under 0.2; plurals 0.94, distinct tags up to 0.71.
    "perplexity/pplx-embed-v1-0.6b": Calibration(0.3, 0.2, 0.85),
}
# For models not measured: bge-small's values.
DEFAULT_CALIBRATION = CALIBRATIONS[DEFAULT_EMBEDDING_MODEL]


def calibration(settings: Settings | None = None) -> Calibration:
    """The calibration of the configured embedding model, with any value set in the
    settings (`SIMILARITY_FLOOR`, `TOPIC_SIMILARITY_FLOOR`, `TAG_MERGE_THRESHOLD`) instead
    of the measured one."""
    settings = settings or get_settings()
    measured = CALIBRATIONS.get(settings.embedding_model)
    if measured is None:
        logger.warning(
            "No calibration for embedding model %s; using %s's (set SIMILARITY_FLOOR, "
            "TOPIC_SIMILARITY_FLOOR and TAG_MERGE_THRESHOLD to tune)",
            settings.embedding_model,
            DEFAULT_EMBEDDING_MODEL,
        )
        measured = DEFAULT_CALIBRATION
    return Calibration(
        similarity_floor=_override(settings.similarity_floor, measured.similarity_floor),
        topic_similarity_floor=_override(
            settings.topic_similarity_floor, measured.topic_similarity_floor
        ),
        tag_merge_threshold=_override(settings.tag_merge_threshold, measured.tag_merge_threshold),
    )


def _override(value: float | None, default: float) -> float:
    return default if value is None else value


class StubEmbeddingProvider:
    """Deterministic pseudo-random unit vectors from a hash of each text. For tests.

    The same text always gets the same vector; different texts get nearly orthogonal
    ones. `vectors` overrides the result for exact texts (normalized on the way out).
    `calls` records every `embed` call's texts.
    """

    def __init__(
        self,
        model: str = "stub-embedding-v1",
        *,
        dimensions: int = EMBEDDING_DIMENSIONS,
        vectors: Mapping[str, Sequence[float]] | None = None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self.vectors = dict(vectors or {})
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[Embedding]:
        self.calls.append(list(texts))
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> Embedding:
        if text in self.vectors:
            return normalize(self.vectors[text])
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        rng = random.Random(seed)
        return normalize([rng.gauss(0.0, 1.0) for _ in range(self.dimensions)])


def normalize(vector: Sequence[float]) -> Embedding:
    """`vector` scaled to unit length."""
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        raise ValueError("Cannot normalize a zero vector")
    return tuple(x / norm for x in vector)


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity in [-1, 1]; for unit vectors (as stored), the dot product."""
    if len(a) != len(b):
        raise ValueError(f"Embeddings differ in length ({len(a)} vs {len(b)})")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norms = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norms if norms else 0.0


# Storage


def store_embedding(session: Session, video_id: str, embedding: Sequence[float]) -> None:
    """Set the stored embedding of `video_id`, replacing any previous one."""
    if len(embedding) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Expected a {EMBEDDING_DIMENSIONS}-dimensional embedding, got {len(embedding)}"
        )
    session.execute(text("DELETE FROM video_embeddings WHERE video_id = :id"), {"id": video_id})
    session.execute(
        text("INSERT INTO video_embeddings (video_id, embedding) VALUES (:id, :embedding)"),
        {"id": video_id, "embedding": serialize_embedding(embedding)},
    )


def get_embedding(session: Session, video_id: str) -> Embedding | None:
    """The stored embedding of `video_id`, or None if it has not been enriched."""
    blob = session.execute(
        text("SELECT embedding FROM video_embeddings WHERE video_id = :id"), {"id": video_id}
    ).scalar_one_or_none()
    return None if blob is None else deserialize_embedding(blob)


def get_embeddings(session: Session, video_ids: Iterable[str]) -> dict[str, Embedding]:
    """Stored embeddings by video id; videos without one are left out."""
    ids = list(dict.fromkeys(video_ids))
    if not ids:
        return {}
    rows = session.execute(
        text("SELECT video_id, embedding FROM video_embeddings WHERE video_id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": ids},
    )
    return {video_id: deserialize_embedding(blob) for video_id, blob in rows}


def serialize_embedding(embedding: Sequence[float]) -> bytes:
    """`embedding` as little-endian float32s, the format sqlite-vec stores."""
    return struct.pack(f"<{len(embedding)}f", *embedding)


def deserialize_embedding(blob: bytes) -> Embedding:
    """The embedding stored in `blob` by `serialize_embedding`."""
    return struct.unpack(f"<{len(blob) // 4}f", blob)
