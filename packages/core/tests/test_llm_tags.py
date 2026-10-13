import json
import logging
import math
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.candidates import SUBSCRIPTION, record
from homefeed_core.config import Settings
from homefeed_core.db import open_database
from homefeed_core.embeddings import StubEmbeddingProvider
from homefeed_core.enricher import Enricher, enrich_candidates
from homefeed_core.gateway.fake import FakeGateway, make_captions, make_channel, make_video
from homefeed_core.llm_tags import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OPENROUTER_MODEL,
    SYSTEM_PROMPT,
    TAG_PROMPT_VERSION,
    TOPICS,
    LLMError,
    LLMTags,
    LLMUnavailableError,
    OllamaProvider,
    OpenRouterProvider,
    StubLLMProvider,
    Tagger,
    get_llm_provider,
    get_tags,
    parse_tags,
    store_tags,
)
from homefeed_core.model_features import FEATURE_NAMES, ModelInput, feature_row
from homefeed_core.ratings import set_rating

NOW = datetime(2026, 10, 13, 6, 0, tzinfo=UTC)
CHANNEL = make_channel("UC" + "w" * 22, title="Woodworking", handle="@wood")
VIDEO = make_video(
    "aaaaaaaaaaa",
    channel=CHANNEL,
    title="Cutting dovetails by hand",
    description="How I cut dovetails.",
    tags=("woodworking", "dovetails"),
    duration_seconds=900,
    published_at=NOW - timedelta(days=3),
)
BAIT = make_video(
    "bbbbbbbbbbb", channel=CHANNEL, title="You WON'T BELIEVE this joint", duration_seconds=600
)
DEEP = '{"topic": "crafts_diy", "depth": 0.9, "clickbait": 0.1, "rage_bait": 0}'
BAITY = '{"topic": "crafts_diy", "depth": 0.2, "clickbait": 0.95, "rage_bait": 0.3}'


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def add_videos(sessions: sessionmaker[Session], *video_ids: str) -> None:
    with sessions.begin() as session:
        session.execute(
            text("INSERT OR IGNORE INTO channels (id, title) VALUES (:id, 'Woodworking')"),
            {"id": CHANNEL.id},
        )
        for video_id in video_ids:
            session.execute(
                text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :channel, :id)"),
                {"id": video_id, "channel": CHANNEL.id},
            )


def stored(sessions: sessionmaker[Session], *video_ids: str) -> dict[str, LLMTags]:
    with sessions() as session:
        return get_tags(session, video_ids)


# Parsing


def test_parse_tags_reads_the_json_object() -> None:
    assert parse_tags(DEEP) == LLMTags("crafts_diy", 0.9, 0.1, 0.0)


@pytest.mark.parametrize(
    "answer",
    [
        f"```json\n{DEEP}\n```",
        f"Sure! Here are the tags:\n{DEEP}\nHope that helps.",
        # Reasoning before the answer, mentioning braces of its own.
        "<think>The format is {topic, depth}; it is a woodworking video.</think>\n" + DEEP,
    ],
)
def test_parse_tags_ignores_text_around_the_object(answer: str) -> None:
    assert parse_tags(answer) == LLMTags("crafts_diy", 0.9, 0.1, 0.0)


def test_parse_tags_clips_scores_and_files_unknown_topics_under_other() -> None:
    answer = '{"topic": "Basket weaving", "depth": 7, "clickbait": -1, "rage_bait": "0.4"}'

    assert parse_tags(answer) == LLMTags("other", 1.0, 0.0, 0.4)


def test_parse_tags_normalizes_topic_spelling() -> None:
    assert parse_tags(DEEP.replace("crafts_diy", "Crafts DIY")).topic == "crafts_diy"


@pytest.mark.parametrize(
    "answer",
    [
        "I can't tag this video.",
        '{"topic": "music", "depth": 0.5, "clickbait": 0.1}',  # rage_bait missing
        '{"topic": "music", "depth": "deep", "clickbait": 0, "rage_bait": 0}',
        '{"topic": "music", "depth": NaN, "clickbait": 0, "rage_bait": 0}',
        '["music", 0.5, 0, 0]',
    ],
)
def test_parse_tags_rejects_unusable_answers(answer: str) -> None:
    with pytest.raises(LLMError):
        parse_tags(answer)


# Providers


class FakePost:
    """Records requests and answers them with `answer`."""

    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.requests: list[tuple[str, Mapping[str, Any], Mapping[str, str], float]] = []

    def __call__(
        self, url: str, body: Mapping[str, Any], headers: Mapping[str, str], timeout: float
    ) -> Any:
        self.requests.append((url, body, headers, timeout))
        return self.answer


def chat_completion(content: str | None) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
    }


def test_openrouter_posts_an_openai_chat_completion() -> None:
    post = FakePost(chat_completion(DEEP))
    provider = OpenRouterProvider(
        "sk-or-test",
        model="mistralai/mistral-nemo",
        base_url="https://example.test/api/v1/",
        post=post,
    )

    assert provider.complete("system prompt", "user message") == DEEP

    assert provider.model == "openrouter:mistralai/mistral-nemo"
    [(url, body, headers, timeout)] = post.requests
    assert url == "https://example.test/api/v1/chat/completions"
    assert body["model"] == "mistralai/mistral-nemo"
    assert body["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user message"},
    ]
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0 and body["stream"] is False
    assert headers["Authorization"] == "Bearer sk-or-test"
    assert headers["X-Title"] == "Homefeed"
    assert timeout == 60.0


@pytest.mark.parametrize(
    "answer",
    [
        {"error": {"code": 502, "message": "upstream failed"}},
        {"choices": []},
        chat_completion(None),
        chat_completion(""),
    ],
)
def test_openrouter_rejects_answers_without_text(answer: dict[str, Any]) -> None:
    provider = OpenRouterProvider("sk-or-test", post=FakePost(answer))

    with pytest.raises(LLMError):
        provider.complete("system", "user")


def test_ollama_posts_a_json_mode_chat() -> None:
    post = FakePost({"model": "llama3.1:8b", "message": {"role": "assistant", "content": DEEP}})
    provider = OllamaProvider(post=post)

    assert provider.complete("system prompt", "user message") == DEEP

    assert provider.model == "ollama:llama3.1:8b"
    [(url, body, _, _)] = post.requests
    assert url == f"{DEFAULT_OLLAMA_BASE_URL}/api/chat"
    assert body["format"] == "json" and body["stream"] is False
    assert body["messages"][1] == {"role": "user", "content": "user message"}


def test_no_provider_when_tagging_is_off() -> None:
    assert get_llm_provider(Settings(llm_provider="none")) is None


@pytest.mark.parametrize("key", [None, SecretStr(""), SecretStr("  ")])
def test_openrouter_without_a_key_is_skipped_with_a_warning(
    key: SecretStr | None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        provider = get_llm_provider(Settings(llm_provider="openrouter", openrouter_api_key=key))

    assert provider is None
    assert "OPENROUTER_API_KEY" in caplog.text


def test_configured_providers() -> None:
    openrouter = get_llm_provider(
        Settings(llm_provider="openrouter", openrouter_api_key=SecretStr("sk-or-test"))
    )
    ollama = get_llm_provider(
        Settings(llm_provider="ollama", llm_model="qwen3:8b", llm_base_url="http://gpu:11434")
    )

    assert isinstance(openrouter, OpenRouterProvider)
    assert openrouter.model == f"openrouter:{DEFAULT_OPENROUTER_MODEL}"
    assert isinstance(ollama, OllamaProvider)
    assert ollama.model == "ollama:qwen3:8b"


# Tagging


def test_tagger_tags_and_stores(sessions: sessionmaker[Session]) -> None:
    add_videos(sessions, VIDEO.id)
    provider = StubLLMProvider(default=DEEP)

    report = Tagger(sessions, provider, now=lambda: NOW).tag_many([VIDEO.id])

    assert report.tagged == [VIDEO.id]
    assert stored(sessions, VIDEO.id) == {VIDEO.id: LLMTags("crafts_diy", 0.9, 0.1, 0.0)}
    [(system, user)] = provider.calls
    assert system == SYSTEM_PROMPT
    assert user.startswith(f"Title: {VIDEO.id}")
    with sessions() as session:
        row = session.execute(
            text("SELECT prompt_version, model, tagged_at FROM video_llm_tags")
        ).one()
    assert tuple(row) == (TAG_PROMPT_VERSION, "stub-llm-v1", "2026-10-13T06:00:00.000Z")


def test_cache_hits_skip_the_provider(sessions: sessionmaker[Session]) -> None:
    add_videos(sessions, VIDEO.id)
    provider = StubLLMProvider()
    tagger = Tagger(sessions, provider)

    tagger.tag_many([VIDEO.id])
    report = tagger.tag_many([VIDEO.id])

    assert report.cached == [VIDEO.id] and report.tagged == []
    assert len(provider.calls) == 1


def test_tags_are_cached_per_prompt_version(sessions: sessionmaker[Session]) -> None:
    add_videos(sessions, VIDEO.id)
    with sessions.begin() as session:
        old = LLMTags("music", 0.1, 0.9, 0.9)
        store_tags(session, VIDEO.id, old, model="old", prompt_version=TAG_PROMPT_VERSION - 1)
    provider = StubLLMProvider(default=DEEP)

    # Tags of another prompt version are not used, and the video is retagged.
    assert stored(sessions, VIDEO.id) == {}
    report = Tagger(sessions, provider).tag_many([VIDEO.id])

    assert report.tagged == [VIDEO.id]
    assert stored(sessions, VIDEO.id)[VIDEO.id].topic == "crafts_diy"
    with sessions() as session:
        previous = get_tags(session, [VIDEO.id], prompt_version=TAG_PROMPT_VERSION - 1)
    assert previous == {VIDEO.id: old}


def test_unusable_answers_are_recorded_and_retried(sessions: sessionmaker[Session]) -> None:
    add_videos(sessions, VIDEO.id, BAIT.id)
    provider = StubLLMProvider(answers={VIDEO.id: "no idea"}, default=BAITY)
    tagger = Tagger(sessions, provider)

    report = tagger.tag_many([VIDEO.id, BAIT.id])

    assert report.tagged == [BAIT.id]
    assert list(report.failed) == [VIDEO.id]
    assert VIDEO.id not in stored(sessions, VIDEO.id)

    provider.answers = {}
    assert tagger.tag_many([VIDEO.id, BAIT.id]).tagged == [VIDEO.id]


def test_an_unavailable_provider_stops_the_run(sessions: sessionmaker[Session]) -> None:
    add_videos(sessions, VIDEO.id, BAIT.id, "ccccccccccc")
    provider = StubLLMProvider(answers={BAIT.id: LLMUnavailableError("HTTP 401: bad key")})

    report = Tagger(sessions, provider).tag_many([VIDEO.id, BAIT.id, "ccccccccccc"])

    assert report.tagged == [VIDEO.id]
    assert list(report.failed) == [BAIT.id]
    assert report.skipped == ["ccccccccccc"]
    assert report.stopped is not None and "401" in report.stopped
    assert len(provider.calls) == 2


def test_videos_without_metadata_are_skipped(sessions: sessionmaker[Session]) -> None:
    provider = StubLLMProvider()

    report = Tagger(sessions, provider).tag_many(["zzzzzzzzzzz"])

    assert report.skipped == ["zzzzzzzzzzz"]
    assert provider.calls == []


def test_tagging_is_capped_per_run(sessions: sessionmaker[Session]) -> None:
    ids = [f"v{i:010d}" for i in range(5)]
    add_videos(sessions, *ids)
    provider = StubLLMProvider()

    report = Tagger(sessions, provider, max_per_run=2).tag_many(ids)

    assert report.tagged == ids[:2]
    assert report.skipped == ids[2:]


# Enrichment


@pytest.fixture
def gateway() -> FakeGateway:
    fake = FakeGateway()
    fake.add_channel(CHANNEL, [VIDEO, BAIT])
    fake.add_captions(make_captions(VIDEO.id, ["first we mark the tails"], seconds_per_line=10))
    return fake


def test_enrich_candidates_tags_candidates_and_rated_videos(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    rated = make_video("rrrrrrrrrrr", channel=CHANNEL, title="A middling video")
    gateway.add_video(rated)
    add_videos(sessions, VIDEO.id, rated.id)
    with sessions.begin() as session:
        record(session, [VIDEO.id], source=SUBSCRIPTION, now=NOW - timedelta(hours=1))
        set_rating(session, rated.id, 4.7)
    provider = StubLLMProvider(default=DEEP)
    enricher = Enricher(
        sessions, gateway, StubEmbeddingProvider(), tagger=Tagger(sessions, provider)
    )

    report = enrich_candidates(enricher=enricher, sessions=sessions, settings=Settings(), now=NOW)

    assert report.enriched == [VIDEO.id]
    assert report.tags is not None and report.tags.tagged == [VIDEO.id, rated.id]
    assert set(stored(sessions, VIDEO.id, rated.id)) == {VIDEO.id, rated.id}
    # Tagged after enrichment, so the prompt has the enriched metadata and transcript.
    prompt = provider.calls[0][1]
    assert "Title: Cutting dovetails by hand" in prompt
    assert "Tags: woodworking, dovetails" in prompt
    assert "first we mark the tails" in prompt


def test_tagging_errors_never_fail_enrichment(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    class Broken(StubLLMProvider):
        def complete(self, system: str, user: str) -> str:
            raise RuntimeError("bug")

    add_videos(sessions, VIDEO.id)
    with sessions.begin() as session:
        record(session, [VIDEO.id], source=SUBSCRIPTION, now=NOW - timedelta(hours=1))
    enricher = Enricher(
        sessions, gateway, StubEmbeddingProvider(), tagger=Tagger(sessions, Broken())
    )

    report = enrich_candidates(enricher=enricher, sessions=sessions, settings=Settings(), now=NOW)

    assert report.enriched == [VIDEO.id]
    assert report.tags is None


def test_no_tagging_without_a_tagger(sessions: sessionmaker[Session], gateway: FakeGateway) -> None:
    enricher = Enricher(sessions, gateway, StubEmbeddingProvider())

    report = enrich_candidates(enricher=enricher, sessions=sessions, settings=Settings(), now=NOW)

    assert report.tags is None


# Features


def test_tags_become_model_features() -> None:
    tags = LLMTags("music", 0.8, 0.25, 0.5)
    row = dict(zip(FEATURE_NAMES, feature_row(ModelInput("v", tags=tags)), strict=True))

    assert row["has_llm_tags"] == 1.0
    assert (row["llm_depth"], row["llm_clickbait"], row["llm_rage_bait"]) == (0.8, 0.25, 0.5)
    assert [row[f"llm_topic_{topic}"] for topic in TOPICS].count(1.0) == 1
    assert row["llm_topic_music"] == 1.0


def test_untagged_videos_have_unknown_tag_features() -> None:
    row = dict(zip(FEATURE_NAMES, feature_row(ModelInput("v")), strict=True))

    assert row["has_llm_tags"] == 0.0
    assert all(math.isnan(row[name]) for name in FEATURE_NAMES if name.startswith("llm_"))


def test_stub_answers_are_valid_json() -> None:
    assert json.loads(StubLLMProvider().default)["topic"] in TOPICS
