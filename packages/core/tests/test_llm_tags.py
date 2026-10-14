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

from homefeed_core import llm_tags
from homefeed_core.candidates import SUBSCRIPTION, record
from homefeed_core.config import Settings, get_settings
from homefeed_core.db import get_session_factory, open_database
from homefeed_core.embeddings import StubEmbeddingProvider
from homefeed_core.enricher import Enricher, enrich_candidates
from homefeed_core.gateway.fake import FakeGateway, make_captions, make_channel, make_video
from homefeed_core.llm_tags import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OPENROUTER_MODEL,
    SYSTEM_PROMPT,
    TAG_PROMPT_VERSION,
    TOPICS,
    Completion,
    LLMError,
    LLMTags,
    LLMUnavailableError,
    OllamaProvider,
    OpenRouterProvider,
    StubLLMProvider,
    Tagger,
    TokenUsage,
    get_llm_provider,
    get_scores,
    get_tags,
    parse_answer,
    store_tags,
    system_prompt,
)
from homefeed_core.model_features import FEATURE_NAMES, ModelInput, feature_row
from homefeed_core.ratings import set_rating
from homefeed_core.tags import ProposedTag, VideoTag, get_video_tags, set_llm_tags
from homefeed_core.user_settings import default_user_settings, update_user_settings

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
DEEP = (
    '{"topic": "crafts_diy", "depth": 0.9, "clickbait": 0.1, "rage_bait": 0, "tags": ['
    '{"tag": "woodworking", "confidence": 0.95}, {"tag": "Dovetail joints", "confidence": 0.8},'
    ' {"tag": "hand tools", "confidence": 0.6}]}'
)
BAITY = (
    '{"topic": "crafts_diy", "depth": 0.2, "clickbait": 0.95, "rage_bait": 0.3, "tags": ['
    '{"tag": "woodworking", "confidence": 0.7}]}'
)


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


def stored_tags(sessions: sessionmaker[Session], video_id: str) -> list[tuple[str, float]]:
    """(slug, confidence) of the video's tags, most confident first."""
    with sessions() as session:
        tags = get_video_tags(session, [video_id]).get(video_id, [])
    return [(tag.slug, tag.confidence) for tag in tags]


# Parsing


def test_parse_answer_reads_the_json_object() -> None:
    answer = parse_answer(DEEP)

    assert answer.scores == LLMTags("crafts_diy", 0.9, 0.1, 0.0)
    assert answer.tags == (
        ProposedTag("woodworking", 0.95),
        ProposedTag("Dovetail joints", 0.8),
        ProposedTag("hand tools", 0.6),
    )


@pytest.mark.parametrize(
    "answer",
    [
        f"```json\n{DEEP}\n```",
        f"Sure! Here are the tags:\n{DEEP}\nHope that helps.",
        # Reasoning before the answer, mentioning braces of its own.
        "<think>The format is {topic, depth}; it is a woodworking video.</think>\n" + DEEP,
    ],
)
def test_parse_answer_ignores_text_around_the_object(answer: str) -> None:
    assert parse_answer(answer) == parse_answer(DEEP)


def test_parse_answer_clips_scores_and_files_unknown_topics_under_other() -> None:
    answer = (
        '{"topic": "Basket weaving", "depth": 7, "clickbait": -1, "rage_bait": "0.4", '
        '"tags": ["baskets"]}'
    )

    assert parse_answer(answer).scores == LLMTags("other", 1.0, 0.0, 0.4)


def test_parse_answer_normalizes_topic_spelling() -> None:
    assert parse_answer(DEEP.replace("crafts_diy", "Crafts DIY")).scores.topic == "crafts_diy"


def test_parse_answer_keeps_usable_tags_only() -> None:
    tags = [
        {"tag": "rust", "confidence": 0.9},
        {"tag": "Rust", "confidence": 0.95},  # same slug: the more confident one stays
        {"tag": "#embedded", "confidence": 1.4},  # clipped
        {"tag": "cargo", "confidence": "0.5"},
        {"tag": "!!!", "confidence": 0.9},  # no slug
        {"tag": "a tag that is really a whole sentence about the video", "confidence": 0.9},
        {"tag": 42, "confidence": 0.9},
        None,
    ]
    answer = json.dumps({"topic": "programming", "depth": 1, "clickbait": 0, "rage_bait": 0})

    parsed = parse_answer(answer[:-1] + ', "tags": ' + json.dumps(tags) + "}")

    assert parsed.tags == (
        ProposedTag("#embedded", 1.0),
        ProposedTag("Rust", 0.95),
        ProposedTag("cargo", 0.5),
    )


def test_parse_answer_accepts_bare_strings_and_missing_confidences() -> None:
    # As small models answer: confidence by position, underscores as spaces.
    tags = ["programming", "software_design", {"tag": "dev tools"}, {"tag": "ux", "confidence": 1}]
    answer = {"topic": "programming", "depth": 1, "clickbait": 0, "rage_bait": 0, "tags": tags}

    parsed = parse_answer(json.dumps(answer))

    assert parsed.tags == (
        ProposedTag("ux", 1.0),
        ProposedTag("programming", 0.9),
        ProposedTag("software design", 0.85),
        ProposedTag("dev tools", 0.8),
    )


def test_parse_answer_keeps_the_most_confident_tags() -> None:
    tags = [{"tag": f"tag {i}", "confidence": i / 10} for i in range(10)]
    answer = {"topic": "other", "depth": 0, "clickbait": 0, "rage_bait": 0, "tags": tags}

    parsed = parse_answer(json.dumps(answer))

    assert [tag.label for tag in parsed.tags] == [f"tag {i}" for i in range(9, 1, -1)]


@pytest.mark.parametrize(
    "answer",
    [
        "I can't tag this video.",
        '{"topic": "music", "depth": 0.5, "clickbait": 0.1}',  # rage_bait missing
        '{"topic": "music", "depth": "deep", "clickbait": 0, "rage_bait": 0}',
        '{"topic": "music", "depth": NaN, "clickbait": 0, "rage_bait": 0}',
        '["music", 0.5, 0, 0]',
        # Prompt v1 answers: no tags.
        '{"topic": "music", "depth": 0.5, "clickbait": 0, "rage_bait": 0}',
        '{"topic": "music", "depth": 0.5, "clickbait": 0, "rage_bait": 0, "tags": "music"}',
        # No usable tag: retried rather than stored without tags.
        '{"topic": "music", "depth": 0.5, "clickbait": 0, "rage_bait": 0, "tags": []}',
        '{"topic": "music", "depth": 0.5, "clickbait": 0, "rage_bait": 0, "tags": ["!!!"]}',
    ],
)
def test_parse_answer_rejects_unusable_answers(answer: str) -> None:
    with pytest.raises(LLMError):
        parse_answer(answer)


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


def chat_completion(content: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        **extra,
    }


def test_openrouter_posts_an_openai_chat_completion() -> None:
    post = FakePost(chat_completion(DEEP))
    provider = OpenRouterProvider(
        "sk-or-test",
        model="mistralai/mistral-nemo",
        base_url="https://example.test/api/v1/",
        post=post,
    )

    assert provider.complete("system prompt", "user message") == Completion(DEEP)

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
    assert body["usage"] == {"include": True}
    assert headers["Authorization"] == "Bearer sk-or-test"
    assert headers["X-Title"] == "Homefeed"
    assert timeout == 60.0


def test_openrouter_reports_token_usage_and_cost() -> None:
    usage = {"prompt_tokens": 1200, "completion_tokens": 90, "total_tokens": 1290, "cost": 0.0002}
    provider = OpenRouterProvider("sk-or-test", post=FakePost(chat_completion(DEEP, usage=usage)))

    assert provider.complete("system", "user").usage == TokenUsage(1200, 90, 0.0002)


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
    post = FakePost(
        {
            "model": "llama3.1:8b",
            "message": {"role": "assistant", "content": DEEP},
            "prompt_eval_count": 800,
            "eval_count": 70,
        }
    )
    provider = OllamaProvider(post=post)

    assert provider.complete("system prompt", "user message") == Completion(
        DEEP, TokenUsage(800, 70)
    )

    assert provider.model == "ollama:llama3.1:8b"
    [(url, body, _, _)] = post.requests
    assert url == f"{DEFAULT_OLLAMA_BASE_URL}/api/chat"
    assert body["format"] == "json" and body["stream"] is False
    assert body["messages"][1] == {"role": "user", "content": "user message"}


def test_no_provider_when_tagging_is_off() -> None:
    assert get_llm_provider(default_user_settings(Settings(llm_provider="none"))) is None


@pytest.mark.parametrize("key", [None, SecretStr(""), SecretStr("  ")])
def test_openrouter_without_a_key_is_skipped_with_a_warning(
    key: SecretStr | None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        provider = get_llm_provider(
            default_user_settings(Settings(llm_provider="openrouter", openrouter_api_key=key))
        )

    assert provider is None
    assert "OPENROUTER_API_KEY" in caplog.text


def test_configured_providers() -> None:
    openrouter = get_llm_provider(
        default_user_settings(
            Settings(llm_provider="openrouter", openrouter_api_key=SecretStr("sk-or-test"))
        )
    )
    settings = Settings(
        llm_provider="ollama", llm_model="qwen3:8b", llm_base_url="http://gpu:11434"
    )
    ollama = get_llm_provider(default_user_settings(settings), settings)

    assert isinstance(openrouter, OpenRouterProvider)
    assert openrouter.model == f"openrouter:{DEFAULT_OPENROUTER_MODEL}"
    assert isinstance(ollama, OllamaProvider)
    assert ollama.model == "ollama:qwen3:8b"


def test_get_tagger_follows_the_user_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    monkeypatch.setenv("LLM_PROVIDER", "none")
    monkeypatch.setattr(llm_tags, "get_embedding_provider", StubEmbeddingProvider)
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    llm_tags._tagger_for.cache_clear()  # pyright: ignore[reportPrivateUsage]
    try:
        assert llm_tags.get_tagger() is None
        with get_session_factory().begin() as session:
            update_user_settings(
                session,
                {
                    "llm_provider": "openrouter",
                    "openrouter_api_key": "sk-or-test",
                    "llm_model": "qwen/qwen3-8b",
                },
            )
        tagger = llm_tags.get_tagger()
        assert tagger is not None and tagger.model == "openrouter:qwen/qwen3-8b"
        assert llm_tags.get_tagger() is tagger  # the same while the settings are
    finally:
        get_session_factory().kw["bind"].dispose()
        get_settings.cache_clear()
        get_session_factory.cache_clear()
        llm_tags._tagger_for.cache_clear()  # pyright: ignore[reportPrivateUsage]


# Tagging


def test_tagger_tags_and_stores(sessions: sessionmaker[Session]) -> None:
    add_videos(sessions, VIDEO.id)
    provider = StubLLMProvider(default=DEEP)

    report = Tagger(sessions, provider, now=lambda: NOW).tag_many([VIDEO.id])

    assert report.tagged == [VIDEO.id]
    assert stored(sessions, VIDEO.id) == {VIDEO.id: LLMTags("crafts_diy", 0.9, 0.1, 0.0)}
    assert stored_tags(sessions, VIDEO.id) == [
        ("woodworking", 0.95),
        ("dovetail-joints", 0.8),
        ("hand-tools", 0.6),
    ]
    [(system, user)] = provider.calls
    assert system == SYSTEM_PROMPT
    assert user.startswith(f"Title: {VIDEO.id}")
    with sessions() as session:
        row = session.execute(
            text("SELECT prompt_version, model, tagged_at FROM video_llm_tags")
        ).one()
    assert tuple(row) == (TAG_PROMPT_VERSION, "stub-llm-v1", "2026-10-13T06:00:00.000Z")
    with sessions() as session:
        links = session.execute(
            text("SELECT DISTINCT source, prompt_version, tagged_at FROM video_tags")
        ).all()
    assert [tuple(link) for link in links] == [
        ("llm", TAG_PROMPT_VERSION, "2026-10-13T06:00:00.000Z")
    ]


def test_the_prompt_asks_for_specific_tags() -> None:
    assert '"tags": [{"tag": "<tag>", "confidence": <0 to 1>}' in SYSTEM_PROMPT
    assert "3 to 8 specific tags" in SYSTEM_PROMPT


def test_proposed_tags_resolve_to_existing_tags(sessions: sessionmaker[Session]) -> None:
    add_videos(sessions, VIDEO.id, BAIT.id)
    provider = StubLLMProvider(
        answers={BAIT.id: DEEP.replace('"woodworking"', '"Wood-Working"')}, default=DEEP
    )

    Tagger(sessions, provider).tag_many([VIDEO.id, BAIT.id])

    with sessions() as session:
        tags = get_video_tags(session, [VIDEO.id, BAIT.id])
    assert tags[VIDEO.id][0] == tags[BAIT.id][0]
    assert tags[BAIT.id][0] == VideoTag(
        tags[VIDEO.id][0].tag_id, "woodworking", "woodworking", "llm", 0.95
    )


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
    assert [slug for slug, _ in stored_tags(sessions, VIDEO.id)] == [
        "woodworking",
        "dovetail-joints",
        "hand-tools",
    ]
    with sessions() as session:
        previous = get_tags(session, [VIDEO.id], prompt_version=TAG_PROMPT_VERSION - 1)
    assert previous == {VIDEO.id: old}


def test_scores_fall_back_to_older_compatible_versions(sessions: sessionmaker[Session]) -> None:
    add_videos(sessions, VIDEO.id, BAIT.id)
    old = LLMTags("crafts_diy", 0.4, 0.2, 0.0)
    new = LLMTags("crafts_diy", 0.9, 0.1, 0.0)
    with sessions.begin() as session:
        store_tags(session, VIDEO.id, old, model="old", prompt_version=TAG_PROMPT_VERSION - 1)
        store_tags(session, BAIT.id, old, model="old", prompt_version=TAG_PROMPT_VERSION - 1)
        store_tags(session, BAIT.id, new, model="new")

    # Until it is retagged, a video keeps its previous answer for the ranker and trainer;
    # once retagged, the current answer wins.
    with sessions() as session:
        assert get_scores(session, [VIDEO.id, BAIT.id]) == {VIDEO.id: old, BAIT.id: new}
        assert get_tags(session, [VIDEO.id, BAIT.id]) == {BAIT.id: new}


def test_tagging_reports_progress_over_the_videos_it_calls_for(
    sessions: sessionmaker[Session],
) -> None:
    add_videos(sessions, VIDEO.id, BAIT.id, "ccccccccccc")
    with sessions.begin() as session:
        store_tags(session, VIDEO.id, LLMTags("other", 0, 0, 0), model="m")  # up to date
    seen: list[tuple[int, int]] = []

    Tagger(sessions, StubLLMProvider(default=DEEP), max_per_run=1).tag_many(
        [VIDEO.id, BAIT.id, "ccccccccccc"], progress=lambda done, total: seen.append((done, total))
    )

    # Two need tagging, the cap allows one call.
    assert seen == [(1, 1)]


def test_unusable_answers_are_recorded_and_retried(sessions: sessionmaker[Session]) -> None:
    add_videos(sessions, VIDEO.id, BAIT.id)
    provider = StubLLMProvider(answers={VIDEO.id: "no idea"}, default=BAITY)
    tagger = Tagger(sessions, provider)

    report = tagger.tag_many([VIDEO.id, BAIT.id])

    assert report.tagged == [BAIT.id]
    assert list(report.failed) == [VIDEO.id]
    assert VIDEO.id not in stored(sessions, VIDEO.id)
    assert stored_tags(sessions, VIDEO.id) == []

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


def test_token_usage_is_logged_per_run(
    sessions: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    add_videos(sessions, VIDEO.id, BAIT.id)
    # Unparseable answers cost tokens too.
    provider = StubLLMProvider(
        answers={VIDEO.id: "no idea"}, default=DEEP, usage=TokenUsage(1000, 50, 0.001)
    )

    with caplog.at_level(logging.INFO, logger="homefeed_core.llm_tags"):
        report = Tagger(sessions, provider).tag_many([VIDEO.id, BAIT.id])

    assert report.usage == TokenUsage(2000, 100, 0.002)
    assert "2 calls used 2000 prompt + 100 completion tokens, cost 0.0020" in caplog.text


def test_token_usage_without_reports() -> None:
    assert TokenUsage(10, 1) + TokenUsage() == TokenUsage(10, 1, None)


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
        set_rating(session, rated.id, 5)
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
        def complete(self, system: str, user: str) -> Completion:
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


def test_prompt_lists_the_most_used_tags(sessions: sessionmaker[Session]) -> None:
    add_videos(sessions, VIDEO.id, BAIT.id, "ccccccccccc")
    provider = StubLLMProvider(default=DEEP)
    tagger = Tagger(sessions, provider)
    tagger.tag_many([VIDEO.id])
    with sessions.begin() as session:
        set_llm_tags(session, "ccccccccccc", [ProposedTag("Rust", 0.9)], prompt_version=1)

    tagger.tag_many([BAIT.id])

    first, second = (system for system, _ in provider.calls)
    assert first == SYSTEM_PROMPT
    assert second == system_prompt(["Dovetail joints", "hand tools", "Rust", "woodworking"])
    assert second.startswith(SYSTEM_PROMPT)
    assert "Dovetail joints; hand tools; Rust; woodworking" in second


def test_tagger_merges_similar_tags_with_its_embedder(sessions: sessionmaker[Session]) -> None:
    add_videos(sessions, VIDEO.id, BAIT.id)
    embedder = StubEmbeddingProvider(
        dimensions=4,
        vectors={"Rust": [1, 0, 0, 0], "rust lang": [0.95, 0.3122499, 0, 0]},
    )

    def answer(tag: str) -> str:
        return json.dumps(
            {
                "topic": "other",
                "depth": 0.5,
                "clickbait": 0,
                "rage_bait": 0,
                "tags": [{"tag": tag, "confidence": 0.9}],
            }
        )

    provider = StubLLMProvider(answers={VIDEO.id: answer("Rust")}, default=answer("rust lang"))
    tagger = Tagger(sessions, provider, embedder=embedder)

    tagger.tag_many([VIDEO.id, BAIT.id])

    assert stored_tags(sessions, VIDEO.id) == [("rust", 0.9)]
    assert stored_tags(sessions, BAIT.id) == [("rust", 0.9)]
