import math
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import open_database
from homefeed_core.embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbeddingProvider,
    SentenceTransformerProvider,
    StubEmbeddingProvider,
    cosine_similarity,
    get_embedding,
    get_embeddings,
    normalize,
    store_embedding,
)


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def unit(index: int) -> tuple[float, ...]:
    return tuple(1.0 if i == index else 0.0 for i in range(EMBEDDING_DIMENSIONS))


def test_providers_implement_the_protocol() -> None:
    providers: list[EmbeddingProvider] = [StubEmbeddingProvider(), SentenceTransformerProvider()]
    assert [p.dimensions for p in providers] == [EMBEDDING_DIMENSIONS] * 2
    assert providers[1].model == "BAAI/bge-small-en-v1.5"


def test_sentence_transformer_provider_loads_nothing_for_no_texts() -> None:
    assert SentenceTransformerProvider().embed([]) == []


def test_stub_is_deterministic_unit_length_and_recorded() -> None:
    stub = StubEmbeddingProvider()

    first, other = stub.embed(["woodworking", "cooking"])
    [again] = stub.embed(["woodworking"])

    assert first == again
    assert len(first) == EMBEDDING_DIMENSIONS
    assert math.isclose(math.fsum(x * x for x in first), 1.0)
    assert abs(cosine_similarity(first, other)) < 0.3  # unrelated texts: near orthogonal
    assert stub.calls == [["woodworking", "cooking"], ["woodworking"]]


def test_stub_overrides_are_normalized() -> None:
    stub = StubEmbeddingProvider(dimensions=3, vectors={"a": [3.0, 0.0, 4.0]})

    assert stub.embed(["a"]) == [(0.6, 0.0, 0.8)]
    assert len(stub.embed(["b"])[0]) == 3


def test_cosine_similarity() -> None:
    assert cosine_similarity([1, 0], [1, 0]) == 1.0
    assert cosine_similarity([1, 0], [0, 2]) == 0.0
    assert cosine_similarity([1, 1], [-1, -1]) == pytest.approx(-1.0)
    assert cosine_similarity([0, 0], [1, 0]) == 0.0
    with pytest.raises(ValueError):
        cosine_similarity([1, 0], [1, 0, 0])
    with pytest.raises(ValueError):
        normalize([0.0, 0.0])


def test_store_and_read_embeddings(sessions: sessionmaker[Session]) -> None:
    vector = StubEmbeddingProvider().embed(["a video"])[0]
    with sessions.begin() as session:
        store_embedding(session, "aaaaaaaaaaa", vector)
        store_embedding(session, "bbbbbbbbbbb", unit(0))
        store_embedding(session, "bbbbbbbbbbb", unit(1))  # replaces

    with sessions() as session:
        stored = get_embedding(session, "aaaaaaaaaaa")
        both = get_embeddings(session, ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"])
        assert get_embedding(session, "ccccccccccc") is None
        assert get_embeddings(session, []) == {}

    assert stored is not None
    assert stored == pytest.approx(vector, abs=1e-6)  # stored as float32
    assert set(both) == {"aaaaaaaaaaa", "bbbbbbbbbbb"}
    assert both["bbbbbbbbbbb"] == unit(1)


def test_store_rejects_other_dimensions(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session, pytest.raises(ValueError, match="384"):
        store_embedding(session, "aaaaaaaaaaa", [1.0, 0.0])
