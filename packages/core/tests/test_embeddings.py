import math
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.config import Settings
from homefeed_core.db import open_database
from homefeed_core.embeddings import (
    CALIBRATIONS,
    EMBEDDING_DIMENSIONS,
    Calibration,
    EmbeddingError,
    EmbeddingProvider,
    FastEmbedProvider,
    OpenRouterEmbeddingProvider,
    StubEmbeddingProvider,
    calibration,
    cosine_similarity,
    get_embedding,
    get_embeddings,
    make_embedding_provider,
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
    providers: list[EmbeddingProvider] = [StubEmbeddingProvider(), FastEmbedProvider()]
    assert [p.dimensions for p in providers] == [EMBEDDING_DIMENSIONS] * 2
    assert providers[1].model == "BAAI/bge-small-en-v1.5"


def test_fastembed_provider_loads_nothing_for_no_texts() -> None:
    assert FastEmbedProvider().embed([]) == []


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


# OpenRouter


class FakePost:
    """Answers embedding requests with vectors `[i + 1, 1, 0, ...]` per input i, in reverse
    index order (the API doesn't promise order); records the requests."""

    def __init__(self, *, dimensions: int = EMBEDDING_DIMENSIONS, answer: Any = None) -> None:
        self.dimensions = dimensions
        self.answer = answer
        self.requests: list[tuple[str, Mapping[str, Any], Mapping[str, str]]] = []

    def __call__(
        self, url: str, body: Mapping[str, Any], headers: Mapping[str, str], timeout: float
    ) -> Any:
        self.requests.append((url, body, headers))
        if self.answer is not None:
            return self.answer
        data = [
            {"index": i, "embedding": [float(i + 1), 1.0] + [0.0] * (self.dimensions - 2)}
            for i in range(len(body["input"]))
        ]
        return {"data": list(reversed(data)), "usage": {"prompt_tokens": 3}}


def openrouter(post: FakePost, **kwargs: Any) -> OpenRouterEmbeddingProvider:
    return OpenRouterEmbeddingProvider(
        "sk-test", model="perplexity/pplx-embed-v1-0.6b", post=post, **kwargs
    )


def test_openrouter_embeds_in_batches_in_input_order() -> None:
    post = FakePost()
    provider = openrouter(post, batch_size=2, base_url="https://example.test/api/v1/")

    vectors = provider.embed(["a", "b", "c"])

    assert [body["input"] for _, body, _ in post.requests] == [["a", "b"], ["c"]]
    url, body, headers = post.requests[0]
    assert url == "https://example.test/api/v1/embeddings"
    assert body["model"] == "perplexity/pplx-embed-v1-0.6b"
    assert body["dimensions"] == EMBEDDING_DIMENSIONS
    assert headers["Authorization"] == "Bearer sk-test"
    # Ordered by index and normalized: the second of a batch is [2, 1]/sqrt(5).
    assert vectors[1][:2] == pytest.approx((2 / math.sqrt(5), 1 / math.sqrt(5)))
    assert vectors[2][:2] == pytest.approx((1 / math.sqrt(2), 1 / math.sqrt(2)))
    assert all(math.isclose(math.sqrt(sum(x * x for x in v)), 1.0) for v in vectors)
    assert provider.embed([]) == []


def test_openrouter_rejects_other_dimensions() -> None:
    # A model that can't shorten its vectors answers with its own size.
    with pytest.raises(EmbeddingError, match="1024 dimensions"):
        openrouter(FakePost(dimensions=1024)).embed(["a"])


@pytest.mark.parametrize(
    "answer",
    [
        {"error": {"message": "No such model"}},
        {"data": [{"index": 0}]},
        {"data": []},  # fewer vectors than texts
        {"data": [{"index": 0, "embedding": [0.0] * EMBEDDING_DIMENSIONS}]},
    ],
)
def test_openrouter_rejects_unusable_answers(answer: Any) -> None:
    with pytest.raises(EmbeddingError):
        openrouter(FakePost(answer=answer)).embed(["a"])


def test_the_provider_follows_the_settings(tmp_path: Path) -> None:
    local = make_embedding_provider(Settings(data_dir=tmp_path))
    remote = make_embedding_provider(
        Settings(
            embedding_provider="openrouter",
            embedding_model="perplexity/pplx-embed-v1-0.6b",
            openrouter_api_key=SecretStr("sk-test"),
        )
    )

    assert isinstance(local, FastEmbedProvider)
    assert local.model == "BAAI/bge-small-en-v1.5"
    assert isinstance(remote, OpenRouterEmbeddingProvider)
    assert remote.model == "perplexity/pplx-embed-v1-0.6b"
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        make_embedding_provider(Settings(embedding_provider="openrouter", openrouter_api_key=None))


# Calibration


def test_calibration_is_per_model_with_overrides() -> None:
    pplx = "perplexity/pplx-embed-v1-0.6b"

    assert calibration(Settings()) == CALIBRATIONS["BAAI/bge-small-en-v1.5"]
    assert calibration(Settings(embedding_model=pplx)) == CALIBRATIONS[pplx]
    assert calibration(Settings(embedding_model=pplx, tag_merge_threshold=0.9)) == Calibration(
        CALIBRATIONS[pplx].similarity_floor, CALIBRATIONS[pplx].topic_similarity_floor, 0.9
    )
    # An unmeasured model gets bge-small's values (and a warning).
    assert (
        calibration(Settings(embedding_model="some/other-model"))
        == CALIBRATIONS["BAAI/bge-small-en-v1.5"]
    )
