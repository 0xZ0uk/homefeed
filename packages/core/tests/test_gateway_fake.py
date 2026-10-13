"""The in-memory FakeGateway behaves like the real one for the code that uses it."""

import pytest

from homefeed_core.gateway import (
    Gateway,
    RateLimitedError,
    ResolvedChannel,
    ResolvedVideo,
    UnavailableError,
    UnsupportedUrlError,
)
from homefeed_core.gateway.fake import (
    FakeGateway,
    make_captions,
    make_channel,
    make_format,
    make_video,
)

CHANNEL = make_channel("UC" + "a" * 22, title="Woodworking", handle="@wood")


@pytest.fixture
def gateway() -> FakeGateway:
    fake = FakeGateway()
    fake.add_channel(
        CHANNEL,
        [make_video("aaaaaaaaaaa", channel=CHANNEL), make_video("bbbbbbbbbbb", channel=CHANNEL)],
    )
    fake.add_video(make_video("ccccccccccc"), formats=[make_format("140"), make_format("251")])
    return fake


def test_is_a_gateway(gateway: FakeGateway) -> None:
    typed: Gateway = gateway
    assert typed is gateway


def test_serves_added_captions(gateway: FakeGateway) -> None:
    captions = make_captions("aaaaaaaaaaa", ["Hello.", "Today: dovetails."])
    gateway.add_captions(captions)

    assert gateway.get_captions("aaaaaaaaaaa") == captions
    assert captions.text() == "Hello. Today: dovetails."
    assert captions.text(until_seconds=5) == "Hello."
    assert gateway.get_captions("bbbbbbbbbbb") is None
    with pytest.raises(UnavailableError):
        gateway.get_captions("zzzzzzzzzzz")
    assert ("get_captions", "aaaaaaaaaaa") in gateway.calls


def test_serves_added_videos_and_formats(gateway: FakeGateway) -> None:
    assert gateway.get_video("aaaaaaaaaaa").channel_id == CHANNEL.id
    assert [f.itag for f in gateway.get_formats("ccccccccccc")] == ["140", "251"]
    assert gateway.get_formats("aaaaaaaaaaa") == []
    with pytest.raises(UnavailableError):
        gateway.get_video("zzzzzzzzzzz")
    with pytest.raises(UnavailableError):
        gateway.get_formats("zzzzzzzzzzz")


def test_serves_added_related_videos(gateway: FakeGateway) -> None:
    other = make_channel("UC" + "o" * 22, title="Other", handle="@other")
    gateway.add_related(
        "aaaaaaaaaaa",
        [make_video("ddddddddddd", channel=other), make_video("eeeeeeeeeee", channel=other)],
    )

    related = gateway.get_related("aaaaaaaaaaa")
    assert [(v.id, v.channel_id, v.channel_handle) for v in related] == [
        ("ddddddddddd", other.id, "@other"),
        ("eeeeeeeeeee", other.id, "@other"),
    ]
    assert [v.id for v in gateway.get_related("aaaaaaaaaaa", limit=1)] == ["ddddddddddd"]
    assert gateway.get_video("ddddddddddd").channel_id == other.id
    assert gateway.get_related("bbbbbbbbbbb") == []
    with pytest.raises(UnavailableError):
        gateway.get_related("zzzzzzzzzzz")


def test_serves_added_featured_channels(gateway: FakeGateway) -> None:
    other = make_channel("UC" + "o" * 22, title="Other", handle="@other")
    gateway.add_featured(CHANNEL.id, [other], subscriber_count=1200)

    [featured] = gateway.get_featured_channels(CHANNEL.id)
    assert (featured.id, featured.title, featured.handle, featured.subscriber_count) == (
        other.id,
        "Other",
        "@other",
        1200,
    )
    with pytest.raises(UnavailableError):
        gateway.get_featured_channels(other.id)  # featured, but not added


def test_channel_uploads_in_order_with_limit(gateway: FakeGateway) -> None:
    uploads = gateway.get_channel_uploads(CHANNEL.id)
    assert uploads.channel == CHANNEL
    assert [v.id for v in uploads.videos] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert [v.id for v in gateway.get_channel_uploads(CHANNEL.id, limit=1).videos] == [
        "aaaaaaaaaaa"
    ]
    with pytest.raises(UnavailableError):
        gateway.get_channel_uploads("UC" + "z" * 22)


def test_resolves_urls(gateway: FakeGateway) -> None:
    assert gateway.resolve_url("https://www.youtube.com/@Wood") == ResolvedChannel(CHANNEL)
    assert gateway.resolve_url(f"https://www.youtube.com/channel/{CHANNEL.id}") == (
        ResolvedChannel(CHANNEL)
    )
    assert gateway.resolve_url("https://youtu.be/aaaaaaaaaaa") == ResolvedVideo("aaaaaaaaaaa")
    with pytest.raises(UnavailableError):
        gateway.resolve_url("https://www.youtube.com/@nobody")
    with pytest.raises(UnsupportedUrlError):
        gateway.resolve_url("https://example.com/")

    gateway.add_url("https://www.youtube.com/c/woodworking", ResolvedChannel(CHANNEL))
    assert gateway.resolve_url("https://www.youtube.com/c/woodworking") == ResolvedChannel(CHANNEL)


def test_injected_failures_and_call_log(gateway: FakeGateway) -> None:
    gateway.fail("get_video", "aaaaaaaaaaa", RateLimitedError("slow down"))

    with pytest.raises(RateLimitedError):
        gateway.get_video("aaaaaaaaaaa")
    gateway.get_video("bbbbbbbbbbb")

    assert gateway.calls == [("get_video", "aaaaaaaaaaa"), ("get_video", "bbbbbbbbbbb")]
