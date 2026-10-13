"""LLM tags for videos: a broad topic, depth, clickbait and rage-bait scores, and 3 to
8 specific tags (e.g. `rust`, `woodworking`, `f1`), each with a confidence.

An `LLMProvider` answers a system prompt plus a user message with text. Two
implementations exist: `OpenRouterProvider`, the hosted OpenRouter API (the default,
OpenAI-compatible chat completions; needs `OPENROUTER_API_KEY`), and `OllamaProvider`, a
local Ollama server. `LLM_PROVIDER=none` turns tagging off. Tests use
`StubLLMProvider`, which needs no network.

`Tagger.tag_many(video_ids)` asks the provider to tag each video from its stored
metadata (title, channel, duration, YouTube tags, description and, once enriched, the
transcript excerpt) and stores the answer: the topic and scores in `video_llm_tags`,
the specific tags through homefeed_core.tags (`set_llm_tags`, which resolves each to a
canonical tag). Answers are cached per video and `TAG_PROMPT_VERSION`: bump it whenever
the prompt or the tag scale changes, so every video is retagged on its next runs (at
most `max_per_run` per run) and only current tags are used. Changing the model alone
doesn't retag.

Each run logs the tokens it used (as reported by the provider, and the cost when
OpenRouter reports it), so a retagging's cost can be checked on the first runs before
the whole library has gone through.

Failures never fail the enrichment job: an answer that can't be parsed is recorded
for that video (and retried next run), and an unreachable or refusing provider
(network error, bad key, rate limit) stops the run until the next one. A provider
that is enabled without an API key is skipped with a warning (`get_llm_provider`).

The ranker and the trainer read the topic and scores with `get_scores` (which falls back
to compatible answers of earlier prompt versions while a bump retags the library) and
hand them to the model as features (see homefeed_core.model_features).
"""

import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Protocol, cast

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.candidates import list_candidates
from homefeed_core.config import OPENROUTER_BASE_URL, Settings, get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.embeddings import EmbeddingProvider, calibration, get_embedding_provider
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.progress import Progress, ProgressLine, configure_cli_logging
from homefeed_core.ratings import list_ratings, tier_rated_video_ids
from homefeed_core.tags import (
    DEFAULT_MERGE_THRESHOLD,
    ProposedTag,
    is_usable,
    set_llm_tags,
    slugify,
    top_tag_labels,
)

logger = logging.getLogger(__name__)

# Version of the tagging prompt and tag scale. Bump on change.
TAG_PROMPT_VERSION = 2
# Oldest prompt version whose topic and scores mean the same as the current ones (v2
# only added specific tags). The ranker and the trainer fall back to answers this old
# while a version bump retags the library (`get_scores`); raise it when the topic list
# or a score scale changes.
SCORES_COMPATIBLE_SINCE = 1
# Broad topics a video is filed under (one each); "other" catches the rest. Each is a
# one-hot model feature, so changing the list changes the features too.
TOPICS = (
    "science",
    "technology",
    "programming",
    "math",
    "engineering",
    "crafts_diy",
    "cooking_food",
    "music",
    "art_design",
    "film_tv",
    "gaming",
    "sports_fitness",
    "health",
    "history",
    "politics_news",
    "business_finance",
    "education",
    "travel_nature",
    "comedy_entertainment",
    "lifestyle",
    "other",
)
# How many specific tags the prompt asks for; extra ones in an answer are dropped.
MIN_TAGS = 3
MAX_TAGS = 8
# How many of the library's most-used tags the prompt lists for the model to reuse.
TOP_TAGS_IN_PROMPT = 200
DESCRIPTION_CHARS = 1500
TRANSCRIPT_CHARS = 4000

DEFAULT_OPENROUTER_BASE_URL = OPENROUTER_BASE_URL
# Cheap, fast, non-reasoning, multilingual and supports JSON mode on OpenRouter.
DEFAULT_OPENROUTER_MODEL = "google/gemini-2.5-flash-lite"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
# Shown for requests in the OpenRouter dashboard (its optional app attribution header).
OPENROUTER_APP_TITLE = "Homefeed"


class LLMError(Exception):
    """A provider call or its answer failed for one video."""


class LLMUnavailableError(LLMError):
    """The provider can't be used right now (unreachable, bad key, rate limited)."""


@dataclass(frozen=True)
class LLMTags:
    topic: str  # one of TOPICS
    depth: float  # 0 = superficial, 1 = in-depth
    clickbait: float  # 0 = the title and description describe it plainly, 1 = pure bait
    rage_bait: float  # 0 = calm, 1 = made to provoke outrage


@dataclass(frozen=True)
class TokenUsage:
    """Tokens used by provider calls, as the provider reports them."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float | None = None  # in OpenRouter credits (USD); None when not reported

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        costs = [cost for cost in (self.cost, other.cost) if cost is not None]
        return TokenUsage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
            sum(costs) if costs else None,
        )


@dataclass(frozen=True)
class Completion:
    text: str
    usage: TokenUsage | None = None  # None when the provider doesn't report it


class LLMProvider(Protocol):
    """Answers a system prompt and a user message with the model's text."""

    # Stored with the tags it produced, e.g. "openrouter:google/gemini-2.5-flash-lite".
    model: str

    def complete(self, system: str, user: str) -> Completion: ...


# Posts a JSON body (url, body, headers, timeout) and returns the decoded JSON answer.
# Raises LLMUnavailableError when the server can't be reached or refuses.
type PostJson = Callable[[str, Mapping[str, Any], Mapping[str, str], float], Any]


def post_json(url: str, body: Mapping[str, Any], headers: Mapping[str, str], timeout: float) -> Any:
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
        if error.code in (401, 403, 429) or error.code >= 500:
            raise LLMUnavailableError(f"HTTP {error.code} from {url}: {detail}") from error
        raise LLMError(f"HTTP {error.code} from {url}: {detail}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise LLMUnavailableError(f"Can't reach {url}: {error}") from error
    except json.JSONDecodeError as error:
        raise LLMError(f"Non-JSON answer from {url}: {error}") from error


class OpenRouterProvider:
    """The hosted OpenRouter API (https://openrouter.ai/docs), through its
    OpenAI-compatible `POST {base_url}/chat/completions` endpoint with a bearer key.

    Asks for JSON mode (`response_format: json_object`); models without it still get
    the prompt's JSON instructions, and `parse_answer` tolerates text around the object.
    Requests carry OpenRouter's optional `X-Title` attribution header, and ask for usage
    accounting so answers report their cost.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_OPENROUTER_MODEL,
        base_url: str = DEFAULT_OPENROUTER_BASE_URL,
        timeout: float = 60.0,
        post: PostJson = post_json,
    ) -> None:
        self.model = f"openrouter:{model}"
        self._model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key
        self._timeout = timeout
        self._post = post

    def complete(self, system: str, user: str) -> Completion:
        answer = self._post(
            self._url,
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0,
                "stream": False,
                "usage": {"include": True},
            },
            {"Authorization": f"Bearer {self._api_key}", "X-Title": OPENROUTER_APP_TITLE},
            self._timeout,
        )
        if isinstance(answer, dict) and "error" in answer:
            # OpenRouter can report a failed upstream call in a 200 response.
            raise LLMError(f"OpenRouter error: {str(cast(Any, answer)['error'])[:300]}")
        try:
            content = answer["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LLMError(f"Unexpected chat completion: {str(answer)[:300]}") from error
        if not isinstance(content, str) or not content.strip():
            raise LLMError("The chat completion has no text content")
        usage = answer.get("usage")
        if not isinstance(usage, dict):
            return Completion(content)
        usage = cast(dict[str, Any], usage)
        cost = usage.get("cost")
        return Completion(
            content,
            TokenUsage(
                _count(usage.get("prompt_tokens")),
                _count(usage.get("completion_tokens")),
                float(cost)
                if isinstance(cost, int | float) and not isinstance(cost, bool)
                else None,
            ),
        )


class OllamaProvider:
    """A local Ollama server, through `POST {base_url}/api/chat` in JSON mode."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_OLLAMA_MODEL,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        timeout: float = 60.0,
        post: PostJson = post_json,
    ) -> None:
        self.model = f"ollama:{model}"
        self._model = model
        self._url = base_url.rstrip("/") + "/api/chat"
        self._timeout = timeout
        self._post = post

    def complete(self, system: str, user: str) -> Completion:
        answer = self._post(
            self._url,
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            },
            {},
            self._timeout,
        )
        try:
            content = answer["message"]["content"]
        except (KeyError, TypeError) as error:
            raise LLMError(f"Unexpected Ollama answer: {str(answer)[:300]}") from error
        if not isinstance(content, str) or not content.strip():
            raise LLMError("The Ollama answer has no text content")
        return Completion(
            content,
            TokenUsage(_count(answer.get("prompt_eval_count")), _count(answer.get("eval_count"))),
        )


def _count(value: Any) -> int:
    """A reported token count; 0 when missing or malformed."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


class StubLLMProvider:
    """Answers from a function of the user message (by default, neutral tags and one
    specific tag, "misc"). For tests. `calls` records every (system, user) pair; `answers`
    overrides the answer for user messages containing a key. Each answer reports
    `usage` (100 prompt and 20 completion tokens unless given)."""

    def __init__(
        self,
        model: str = "stub-llm-v1",
        *,
        answers: Mapping[str, str | Exception] | None = None,
        default: str = (
            '{"topic": "other", "depth": 0.5, "clickbait": 0, "rage_bait": 0, "tags": '
            '[{"tag": "misc", "confidence": 0.5}]}'
        ),
        usage: TokenUsage | None = None,
    ) -> None:
        self.model = model
        self.answers = dict(answers or {})
        self.default = default
        self.usage = usage or TokenUsage(100, 20)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> Completion:
        self.calls.append((system, user))
        for key, answer in self.answers.items():
            if key in user:
                if isinstance(answer, Exception):
                    raise answer
                return Completion(answer, self.usage)
        return Completion(self.default, self.usage)


def get_llm_provider(settings: Settings | None = None) -> LLMProvider | None:
    """The configured provider, or None when tagging is off or can't be set up (logged)."""
    settings = settings or get_settings()
    match settings.llm_provider:
        case "none":
            return None
        case "openrouter":
            key = (
                settings.openrouter_api_key.get_secret_value()
                if settings.openrouter_api_key
                else ""
            )
            if not key.strip():
                logger.warning(
                    "LLM_PROVIDER=openrouter but OPENROUTER_API_KEY is not set; skipping tagging"
                )
                return None
            return OpenRouterProvider(
                key.strip(),
                model=settings.llm_model or DEFAULT_OPENROUTER_MODEL,
                base_url=settings.llm_base_url or DEFAULT_OPENROUTER_BASE_URL,
                timeout=settings.llm_timeout_seconds,
            )
        case "ollama":
            return OllamaProvider(
                model=settings.llm_model or DEFAULT_OLLAMA_MODEL,
                base_url=settings.llm_base_url or DEFAULT_OLLAMA_BASE_URL,
                timeout=settings.llm_timeout_seconds,
            )


# Prompt

SYSTEM_PROMPT = f"""You tag YouTube videos for a personal recommender. Given a video's
metadata and the start of its transcript, answer with one JSON object and nothing else:

{{"topic": "<one of: {", ".join(TOPICS)}>",
 "depth": <0 to 1>, "clickbait": <0 to 1>, "rage_bait": <0 to 1>,
 "tags": [{{"tag": "<tag>", "confidence": <0 to 1>}}, ...]}}

- topic: the single best-fitting broad topic from the list ("other" if none fits).
- tags: {MIN_TAGS} to {MAX_TAGS} specific tags for what the video is about, most relevant
  first, as someone would search for them: subjects, techniques, tools, games, sports,
  people, places (e.g. "rust", "woodworking", "dovetail joints", "f1", "sourdough").
  One to three words each, in English, lowercase except names and acronyms, no "#".
  Not the format or tone ("tutorial", "review", "funny"). confidence: 1 = clearly
  what the video is about, 0.5 = a side subject.
- depth: 0 = superficial (reactions, listicles, hype), 0.5 = solid overview,
  1 = in-depth, expert, carefully researched.
- clickbait: 0 = the title and description plainly say what the video is,
  1 = they exaggerate, withhold or misrepresent it to get clicks.
- rage_bait: 0 = calm and fair, 1 = made to provoke anger or outrage.
Judge the content, not whether you agree with it."""


def system_prompt(existing_tags: Sequence[str] = ()) -> str:
    """`SYSTEM_PROMPT`, plus the library's most-used tags (`top_tag_labels`) when there
    are any, so the model reuses them rather than coining variants. The list comes last
    so the fixed part stays a cacheable prefix, and the tagger builds it once per run so
    all of a run's prompts share it. It isn't part of the answer format, so it doesn't
    change `TAG_PROMPT_VERSION`."""
    if not existing_tags:
        return SYSTEM_PROMPT
    return (
        f"{SYSTEM_PROMPT}\n\nTags already used in this library:\n"
        + "; ".join(existing_tags)
        + "\nPrefer one of these, spelled exactly like this, when it fits what the video is "
        "about. Add a new tag only when none of them does."
    )


@dataclass(frozen=True)
class TagAnswer:
    """What a model answered for one video."""

    scores: LLMTags  # topic, depth, clickbait, rage-bait
    tags: tuple[ProposedTag, ...]  # most confident first, at most MAX_TAGS


@dataclass(frozen=True)
class TagInput:
    """What a video is tagged from."""

    video_id: str
    title: str
    channel_title: str | None = None
    duration_seconds: int | None = None
    youtube_tags: tuple[str, ...] = ()
    description: str | None = None
    transcript_excerpt: str | None = None


def tag_prompt(video: TagInput) -> str:
    """The user message for tagging `video`. Bump `TAG_PROMPT_VERSION` when changing it."""
    parts = [f"Title: {video.title}"]
    if video.channel_title:
        parts.append(f"Channel: {video.channel_title}")
    if video.duration_seconds is not None:
        parts.append(f"Duration: {round(video.duration_seconds / 60)} minutes")
    if video.youtube_tags:
        parts.append("Tags: " + ", ".join(video.youtube_tags))
    if video.description:
        parts.append("Description:\n" + video.description[:DESCRIPTION_CHARS].strip())
    if video.transcript_excerpt:
        parts.append("Transcript start:\n" + video.transcript_excerpt[:TRANSCRIPT_CHARS].strip())
    return "\n\n".join(parts)


def parse_answer(answer: str) -> TagAnswer:
    """The tags in a model's answer: the last JSON object in it with a "topic" (code
    fences, reasoning and other text around it are ignored). Scores are clipped to
    [0, 1]; an unknown topic is "other". Raises LLMError when there is no usable object,
    including one without a "tags" list; unusable entries in the list are dropped (see
    `_proposed_tags`)."""
    decoder = json.JSONDecoder()
    data: dict[str, Any] | None = None
    for start in (i for i, char in enumerate(answer) if char == "{"):
        try:
            value, _ = decoder.raw_decode(answer, start)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "topic" in value:
            data = cast(dict[str, Any], value)
    if data is None:
        raise LLMError(f"No tags object in the answer: {answer[:200]!r}")
    fields = data
    topic = str(fields.get("topic", "")).strip().lower().replace(" ", "_").replace("-", "_")
    scores = LLMTags(
        topic=topic if topic in TOPICS else "other",
        depth=_score(fields, "depth"),
        clickbait=_score(fields, "clickbait"),
        rage_bait=_score(fields, "rage_bait"),
    )
    return TagAnswer(scores, _proposed_tags(fields.get("tags")))


def _proposed_tags(value: Any) -> tuple[ProposedTag, ...]:
    """The usable entries of an answer's "tags": objects with a "tag" that can be a tag
    (`homefeed_core.tags.is_usable`) and a "confidence" (clipped to [0, 1]). Small models
    often answer with bare strings, or leave the confidence out: those get
    `_positional_confidence`, since the prompt asks for the most relevant first.
    Underscores read as spaces ("software_design"). Spellings with the same slug keep the
    highest confidence; past MAX_TAGS the least confident are dropped. Raises LLMError
    when no entry is usable, so the video is tried again."""
    if not isinstance(value, list):
        raise LLMError(f"Missing or non-list 'tags': {value!r}"[:200])
    best: dict[str, ProposedTag] = {}
    for index, entry in enumerate(cast(list[Any], value)):
        if isinstance(entry, dict):
            entry = cast(dict[str, Any], entry)
            label = entry.get("tag")
            try:
                confidence = _score(entry, "confidence")
            except LLMError:
                confidence = _positional_confidence(index)
        else:
            label, confidence = entry, _positional_confidence(index)
        if not isinstance(label, str):
            continue
        label = label.replace("_", " ")
        if not is_usable(label):
            continue
        slug = slugify(label)
        if slug not in best or best[slug].confidence < confidence:
            best[slug] = ProposedTag(label, confidence)
    if not best:
        raise LLMError(f"No usable tags in {value!r}"[:200])
    ranked = sorted(best.values(), key=lambda tag: -tag.confidence)  # stable: ties keep order
    return tuple(ranked[:MAX_TAGS])


def _positional_confidence(index: int) -> float:
    """The confidence of a tag given without one: 0.9 for the first, 0.05 less for each
    next, down to 0.5."""
    return max(0.5, 0.9 - 0.05 * index)


def _score(data: Mapping[str, Any], name: str) -> float:
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise LLMError(f"Missing or non-numeric {name!r}: {value!r}")
    try:
        score = float(value)
    except ValueError as error:
        raise LLMError(f"Non-numeric {name!r}: {value!r}") from error
    if score != score:  # NaN
        raise LLMError(f"Non-numeric {name!r}: {value!r}")
    return min(1.0, max(0.0, score))


# Storage


def get_tags(
    session: Session, video_ids: Iterable[str], *, prompt_version: int = TAG_PROMPT_VERSION
) -> dict[str, LLMTags]:
    """Stored tags of the current prompt version by video id; untagged videos are left
    out."""
    ids = list(dict.fromkeys(video_ids))
    if not ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT video_id, topic, depth, clickbait, rage_bait FROM video_llm_tags
            WHERE prompt_version = :version AND video_id IN :ids
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"version": prompt_version, "ids": ids},
    )
    return {
        video_id: LLMTags(topic=topic, depth=depth, clickbait=clickbait, rage_bait=rage_bait)
        for video_id, topic, depth, clickbait, rage_bait in rows
    }


def get_scores(session: Session, video_ids: Iterable[str]) -> dict[str, LLMTags]:
    """The newest stored topic and scores by video id, from any prompt version since
    `SCORES_COMPATIBLE_SINCE`, so videos keep their features while a prompt version
    bump retags the library. Untagged videos are left out."""
    ids = list(dict.fromkeys(video_ids))
    if not ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT video_id, topic, depth, clickbait, rage_bait FROM video_llm_tags AS t
            WHERE video_id IN :ids AND prompt_version = (
                SELECT max(prompt_version) FROM video_llm_tags
                WHERE video_id = t.video_id AND prompt_version BETWEEN :since AND :current
            )
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids, "since": SCORES_COMPATIBLE_SINCE, "current": TAG_PROMPT_VERSION},
    )
    return {
        video_id: LLMTags(topic=topic, depth=depth, clickbait=clickbait, rage_bait=rage_bait)
        for video_id, topic, depth, clickbait, rage_bait in rows
    }


def store_tags(
    session: Session,
    video_id: str,
    tags: LLMTags,
    *,
    model: str,
    now: datetime | None = None,
    prompt_version: int = TAG_PROMPT_VERSION,
) -> None:
    """Set the tags of `video_id` for `prompt_version`, replacing earlier ones."""
    session.execute(
        text(
            """
            INSERT INTO video_llm_tags (video_id, prompt_version, model, topic, depth,
                                        clickbait, rage_bait, tagged_at)
            VALUES (:video_id, :version, :model, :topic, :depth, :clickbait, :rage_bait,
                    :tagged_at)
            ON CONFLICT (video_id, prompt_version) DO UPDATE SET
                model = excluded.model,
                topic = excluded.topic,
                depth = excluded.depth,
                clickbait = excluded.clickbait,
                rage_bait = excluded.rage_bait,
                tagged_at = excluded.tagged_at
            """
        ),
        {
            "video_id": video_id,
            "version": prompt_version,
            "model": model,
            "topic": tags.topic,
            "depth": tags.depth,
            "clickbait": tags.clickbait,
            "rage_bait": tags.rage_bait,
            "tagged_at": format_timestamp(now or datetime.now(UTC)),
        },
    )


def load_tag_inputs(session: Session, video_ids: Sequence[str]) -> dict[str, TagInput]:
    """What each stored video among `video_ids` is tagged from; others are left out."""
    if not video_ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT v.id, v.title, c.title, v.duration_seconds, f.tags, v.description,
                   f.transcript_excerpt
            FROM videos AS v
            JOIN channels AS c ON c.id = v.channel_id
            LEFT JOIN video_features AS f ON f.video_id = v.id
            WHERE v.id IN :ids
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": list(video_ids)},
    )
    return {
        video_id: TagInput(
            video_id=video_id,
            title=title,
            channel_title=channel_title,
            duration_seconds=duration,
            youtube_tags=tuple(json.loads(youtube_tags)) if youtube_tags else (),
            description=description,
            transcript_excerpt=excerpt,
        )
        for video_id, title, channel_title, duration, youtube_tags, description, excerpt in rows
    }


# Tagging


@dataclass(frozen=True)
class TagReport:
    tagged: list[str] = field(default_factory=list[str])  # tagged in this run
    cached: list[str] = field(default_factory=list[str])  # already tagged
    skipped: list[str] = field(default_factory=list[str])  # no stored metadata, or over the cap
    failed: dict[str, str] = field(default_factory=dict[str, str])  # video id -> error
    stopped: str | None = None  # why the run stopped early (provider unavailable)
    # Tokens used by this run's answers, unparseable ones included.
    usage: TokenUsage = TokenUsage()


class Tagger:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        provider: LLMProvider,
        *,
        max_per_run: int | None = None,
        embedder: EmbeddingProvider | None = None,
        merge_threshold: float = DEFAULT_MERGE_THRESHOLD,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._provider = provider
        self._max_per_run = max_per_run
        # Tags are embedded and near-duplicates merged (see homefeed_core.tags) only with one.
        self._embedder = embedder
        self._merge_threshold = merge_threshold
        self._now = now

    @property
    def model(self) -> str:
        return self._provider.model

    def tag_many(self, video_ids: Iterable[str], *, progress: Progress | None = None) -> TagReport:
        """Tag the videos without current tags, in order, at most `max_per_run` calls.
        Failures are recorded, not raised. `progress` gets (calls made, calls planned)
        after each call."""
        report = TagReport()
        ids = list(dict.fromkeys(video_ids))
        with self._sessions() as session:
            current = get_tags(session, ids)
            inputs = load_tag_inputs(session, [v for v in ids if v not in current])
            system = system_prompt(top_tag_labels(session, TOP_TAGS_IN_PROMPT))
        planned = sum(1 for v in ids if v not in current and v in inputs)
        if self._max_per_run is not None:
            planned = min(planned, self._max_per_run)
        calls = 0
        usage = TokenUsage()
        for index, video_id in enumerate(ids):
            if video_id in current:
                report.cached.append(video_id)
                continue
            video = inputs.get(video_id)
            if video is None or (self._max_per_run is not None and calls >= self._max_per_run):
                report.skipped.append(video_id)
                continue
            calls += 1
            if progress is not None and calls > 1:
                progress(calls - 1, planned)
            try:
                completion = self._provider.complete(system, tag_prompt(video))
                usage += completion.usage or TokenUsage()
                answer = parse_answer(completion.text)
            except LLMUnavailableError as error:
                logger.warning("LLM tagging stopped (%s): %s", self.model, error)
                report.failed[video_id] = str(error)
                report.skipped.extend(v for v in ids[index + 1 :] if v not in current)
                report = replace(report, stopped=str(error))
                break
            except LLMError as error:
                logger.warning("Could not tag %s: %s", video_id, error)
                report.failed[video_id] = str(error)
                continue
            now = self._now()
            with self._sessions.begin() as session:
                store_tags(session, video_id, answer.scores, model=self.model, now=now)
                set_llm_tags(
                    session,
                    video_id,
                    answer.tags,
                    prompt_version=TAG_PROMPT_VERSION,
                    embedder=self._embedder,
                    threshold=self._merge_threshold,
                    now=now,
                )
            report.tagged.append(video_id)
        if progress is not None and calls:
            progress(calls, planned if report.stopped is None else calls)
        report = replace(report, usage=usage)
        _log(report, self.model)
        return report


def _log(report: TagReport, model: str) -> None:
    usage = report.usage
    calls = len(report.tagged) + len(report.failed)
    logger.info(
        "LLM tagging with %s (prompt v%d): %d tagged, %d up to date, %d skipped, %d failed%s; "
        "%d calls used %d prompt + %d completion tokens%s",
        model,
        TAG_PROMPT_VERSION,
        len(report.tagged),
        len(report.cached),
        len(report.skipped),
        len(report.failed),
        " (stopped early)" if report.stopped else "",
        calls,
        usage.prompt_tokens,
        usage.completion_tokens,
        f", cost {usage.cost:.4f}" if usage.cost is not None else "",
    )


@lru_cache
def get_tagger() -> Tagger | None:
    """The process-wide production tagger, or None when tagging is off or the provider
    isn't configured (warned about once per process)."""
    settings = get_settings()
    provider = get_llm_provider(settings)
    if provider is None:
        return None
    return Tagger(
        get_session_factory(),
        provider,
        max_per_run=settings.llm_max_tags_per_run,
        embedder=get_embedding_provider(),
        merge_threshold=calibration(settings).tag_merge_threshold,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Tag videos now rather than at the worker's next enrichment run:
    `uv run python -m homefeed_core.llm_tags [--all] [--limit N]`. By default it tags what
    the worker would (the next feed's candidates and rated videos); `--all` tags every
    stored video. Videos with tags of the current prompt version are skipped, so it can
    be stopped and run again."""
    parser = argparse.ArgumentParser(
        prog="python -m homefeed_core.llm_tags", description=main.__doc__
    )
    parser.add_argument("--all", action="store_true", help="tag every stored video")
    parser.add_argument("--limit", type=int, help="at most this many LLM calls (default: none)")
    args = parser.parse_args(argv)
    line = ProgressLine()
    configure_cli_logging(line)
    settings = get_settings()
    provider = get_llm_provider(settings)
    if provider is None:
        print("Tagging is off: set LLM_PROVIDER, and OPENROUTER_API_KEY for openrouter.")
        return 1
    sessions = get_session_factory()
    with sessions() as session:
        if args.all:
            video_ids = list(
                session.execute(
                    text("SELECT id FROM videos ORDER BY published_at IS NULL, published_at DESC")
                ).scalars()
            )
        else:
            since = datetime.now(UTC) - timedelta(days=settings.feed_candidate_days)
            video_ids = [c.video_id for c in list_candidates(session, since=since)]
            video_ids += tier_rated_video_ids(session)
            video_ids += [rating.video_id for rating in list_ratings(session)]
    tagger = Tagger(
        sessions,
        provider,
        max_per_run=args.limit,
        embedder=get_embedding_provider(),
        merge_threshold=calibration(settings).tag_merge_threshold,
    )
    report = tagger.tag_many(video_ids, progress=line.phase("Tagging"))
    line.clear()
    usage = report.usage
    print(
        f"{len(report.tagged)} tagged, {len(report.cached)} already tagged, "
        f"{len(report.failed)} failed (tried again next run), "
        f"{len(report.skipped)} skipped (no stored metadata, past --limit, or after a stop)"
        + (f"; stopped: {report.stopped}" if report.stopped else "")
        + f"\n{usage.prompt_tokens} prompt + {usage.completion_tokens} completion tokens"
        + (f", cost ${usage.cost:.4f}" if usage.cost is not None else "")
    )
    return 0 if report.stopped is None else 1


if __name__ == "__main__":
    sys.exit(main())
