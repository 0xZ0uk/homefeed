"""`Gateway.get_comments`: the yt-dlp Gateway against recorded responses, and the fake."""

from datetime import UTC, datetime

import pytest
from gateway_fixtures import Replay

from homefeed_core.gateway import (
    MAX_COMMENTS_LIMIT,
    MemoryEventRecorder,
    RateLimiter,
    RetryPolicy,
    UnavailableError,
    YtDlpGateway,
)
from homefeed_core.gateway.fake import FakeGateway, make_comment, make_video
from homefeed_core.gateway.normalize import comments_from_info
from homefeed_core.gateway.ytdlp import ExtractRequest

ZOO = "jNQXAC9IVRw"


@pytest.fixture
def replay() -> Replay:
    return Replay()


@pytest.fixture
def recorder() -> MemoryEventRecorder:
    return MemoryEventRecorder()


@pytest.fixture
def gateway(replay: Replay, recorder: MemoryEventRecorder) -> YtDlpGateway:
    return YtDlpGateway(
        recorder=recorder,
        retry=RetryPolicy(attempts=3, initial_delay=1.0, jitter=0.0),
        rate_limiter=RateLimiter(0.0),
        extract=replay,
        sleep=lambda _seconds: None,
    )


def test_get_comments(gateway: YtDlpGateway, replay: Replay, recorder: MemoryEventRecorder) -> None:
    comments = gateway.get_comments(ZOO, limit=5)

    assert replay.requests == [
        ExtractRequest(f"https://www.youtube.com/watch?v={ZOO}", limit=5, comments=True)
    ]
    assert len(comments) == 5
    pinned = comments[0]
    assert pinned.id == "UgzuC3zzpRZkjc5Qzsd4AaABAg"
    assert pinned.author == "@SanDiegoZoo"
    assert pinned.author_channel_id == "UCC5NfQ6Mf0dq_eEwv4P_hWA"
    assert pinned.text.startswith("We're so honored")
    assert (pinned.is_pinned, pinned.is_hearted, pinned.author_is_uploader) == (
        True,
        True,
        False,
    )
    assert pinned.like_count == 4_800_000
    assert pinned.published_text == "6 years ago"
    assert pinned.published_at == datetime.fromtimestamp(1602547200, UTC)
    assert pinned.author_thumbnail_url is not None
    assert pinned.author_thumbnail_url.startswith("https://yt3.ggpht.com/")
    assert not any(comment.is_pinned for comment in comments[1:])
    [event] = recorder.events
    assert (event.operation, event.target, event.success) == ("get_comments", ZOO, True)


def test_get_comments_limit_trims_the_response(gateway: YtDlpGateway, replay: Replay) -> None:
    replay.records[
        ExtractRequest(f"https://www.youtube.com/watch?v={ZOO}", limit=2, comments=True)
    ] = replay.records[
        ExtractRequest(f"https://www.youtube.com/watch?v={ZOO}", limit=5, comments=True)
    ]

    assert [c.author for c in gateway.get_comments(ZOO, limit=2)] == ["@SanDiegoZoo", "@Jeff-th5ob"]


def test_get_comments_unavailable_video(
    gateway: YtDlpGateway, recorder: MemoryEventRecorder
) -> None:
    with pytest.raises(UnavailableError):
        gateway.get_comments("xxxxxxxxxxx", limit=5)

    [event] = recorder.events
    assert (event.operation, event.success, event.error_kind) == (
        "get_comments",
        False,
        "unavailable",
    )


@pytest.mark.parametrize("limit", [0, MAX_COMMENTS_LIMIT + 1])
def test_get_comments_rejects_bad_limit(gateway: YtDlpGateway, replay: Replay, limit: int) -> None:
    with pytest.raises(ValueError):
        gateway.get_comments(ZOO, limit=limit)
    assert replay.requests == []


def test_get_comments_rejects_malformed_id(gateway: YtDlpGateway, replay: Replay) -> None:
    with pytest.raises(UnavailableError):
        gateway.get_comments("not-an-id")
    assert replay.requests == []


def test_comments_from_info_skips_replies_duplicates_and_incomplete_entries() -> None:
    root = {"id": "a", "parent": "root", "text": "First", "author": "@x", "author_id": "bad"}
    comments = comments_from_info(
        {
            "id": ZOO,
            "comments": [
                root,
                {"id": "a.1", "parent": "a", "text": "A reply"},
                root,  # duplicate
                {"id": "b", "text": ""},  # no text
                {"text": "No id"},
                "not a comment",
                {"id": "c", "text": "No parent field, no author"},
            ],
        }
    )

    assert [(c.id, c.text, c.author) for c in comments] == [
        ("a", "First", "@x"),
        ("c", "No parent field, no author", ""),
    ]
    assert comments[0].author_channel_id is None  # not a channel id
    assert comments[1].published_at is None


def test_comments_from_info_comments_off() -> None:
    assert comments_from_info({"id": ZOO}) == []
    assert comments_from_info({"id": ZOO, "comments": None}) == []


def test_fake_gateway_serves_added_comments() -> None:
    fake = FakeGateway()
    fake.add_video(make_video("aaaaaaaaaaa"))
    fake.add_video(make_video("bbbbbbbbbbb"))
    fake.add_comments("aaaaaaaaaaa", [make_comment("c1"), make_comment("c2")])

    assert [c.id for c in fake.get_comments("aaaaaaaaaaa")] == ["c1", "c2"]
    assert [c.id for c in fake.get_comments("aaaaaaaaaaa", limit=1)] == ["c1"]
    assert fake.get_comments("bbbbbbbbbbb") == []
    with pytest.raises(UnavailableError):
        fake.get_comments("ccccccccccc")
    with pytest.raises(ValueError):
        fake.get_comments("aaaaaaaaaaa", limit=0)
