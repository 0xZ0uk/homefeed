"""Text embeddings: the provider interface and the stored video embeddings.

Providers turn texts into unit-length vectors. Production uses
`SentenceTransformerProvider` (`BAAI/bge-small-en-v1.5`, 384 dimensions, loaded on
first use); tests use `StubEmbeddingProvider`, which needs no model. A provider's
`model` names what produced a vector and is stored with it, so changing it recomputes.

Video embeddings live in the sqlite-vec table `video_embeddings`; the enricher writes
them, and anything ranking by similarity reads them:

    with sessions() as session:
        vectors = get_embeddings(session, video_ids)  # {video_id: Embedding}
    cosine_similarity(vectors[a], vectors[b])
"""

import hashlib
import math
import random
import struct
import threading
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from homefeed_core.config import get_settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

# Dimension of the `video_embeddings` table (bge-small).
EMBEDDING_DIMENSIONS = 384
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

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


class SentenceTransformerProvider:
    """A sentence-transformers model, downloaded into `cache_dir` and loaded on first use.

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
        self._loaded: SentenceTransformer | None = None
        self._lock = threading.Lock()

    def embed(self, texts: Sequence[str]) -> list[Embedding]:
        if not texts:
            return []
        with self._lock:
            vectors = self._load().encode(  # pyright: ignore[reportUnknownMemberType]
                list(texts),
                batch_size=self._batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        return [tuple(float(x) for x in vector) for vector in vectors]

    def _load(self) -> "SentenceTransformer":
        if self._loaded is None:
            # Imported here: torch takes seconds to import and most processes never embed.
            from sentence_transformers import SentenceTransformer

            loaded = SentenceTransformer(
                self.model,
                device="cpu",
                cache_folder=str(self._cache_dir) if self._cache_dir else None,
            )
            dimensions = loaded.get_embedding_dimension()
            if dimensions != self.dimensions:
                raise ValueError(
                    f"{self.model} makes {dimensions}-dimensional embeddings, "
                    f"expected {self.dimensions}"
                )
            self._loaded = loaded
        return self._loaded


@lru_cache
def get_embedding_provider() -> SentenceTransformerProvider:
    """The process-wide production provider (`EMBEDDING_MODEL`, cached in DATA_DIR/models).

    Shared so a process loads the model at most once, and only when it first embeds
    something: the worker for videos and topics, the API only when a topic's
    description is saved.
    """
    settings = get_settings()
    return SentenceTransformerProvider(
        settings.embedding_model, cache_dir=settings.data_dir / "models"
    )


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
