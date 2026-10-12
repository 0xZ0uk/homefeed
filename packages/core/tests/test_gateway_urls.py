import pytest

from homefeed_core.gateway import ResolvedPlaylist, ResolvedVideo, UnsupportedUrlError
from homefeed_core.gateway.urls import ChannelRef, parse_youtube_url

CHANNEL_ID = "UCHnyfMqiRRG1u-2MsSQLbXA"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/watch?v=jNQXAC9IVRw", ResolvedVideo("jNQXAC9IVRw")),
        ("https://youtube.com/watch?v=jNQXAC9IVRw&list=PL123", ResolvedVideo("jNQXAC9IVRw")),
        ("http://m.youtube.com/watch?v=jNQXAC9IVRw&t=90", ResolvedVideo("jNQXAC9IVRw", 90)),
        ("https://music.youtube.com/watch?v=jNQXAC9IVRw", ResolvedVideo("jNQXAC9IVRw")),
        ("www.youtube.com/watch?v=jNQXAC9IVRw&t=1h2m3s", ResolvedVideo("jNQXAC9IVRw", 3723)),
        ("https://youtu.be/jNQXAC9IVRw", ResolvedVideo("jNQXAC9IVRw")),
        ("https://youtu.be/jNQXAC9IVRw?t=42s", ResolvedVideo("jNQXAC9IVRw", 42)),
        (
            "https://www.youtube.com/shorts/j9p3Sn8ROL4",
            ResolvedVideo("j9p3Sn8ROL4", is_short_url=True),
        ),
        ("https://www.youtube.com/embed/jNQXAC9IVRw?start=7", ResolvedVideo("jNQXAC9IVRw", 7)),
        ("https://www.youtube-nocookie.com/embed/jNQXAC9IVRw", ResolvedVideo("jNQXAC9IVRw")),
        ("https://www.youtube.com/live/jNQXAC9IVRw", ResolvedVideo("jNQXAC9IVRw")),
        ("  https://www.youtube.com/watch?v=jNQXAC9IVRw  ", ResolvedVideo("jNQXAC9IVRw")),
        (
            "https://www.youtube.com/playlist?list=PLFs4vir_WsTwEd-nJgVJCZPNL3HALHHpF",
            ResolvedPlaylist("PLFs4vir_WsTwEd-nJgVJCZPNL3HALHHpF"),
        ),
        (
            f"https://www.youtube.com/channel/{CHANNEL_ID}",
            ChannelRef(f"https://www.youtube.com/channel/{CHANNEL_ID}", CHANNEL_ID),
        ),
        (
            f"https://www.youtube.com/channel/{CHANNEL_ID}/videos",
            ChannelRef(f"https://www.youtube.com/channel/{CHANNEL_ID}", CHANNEL_ID),
        ),
        ("https://www.youtube.com/@veritasium", ChannelRef("https://www.youtube.com/@veritasium")),
        (
            "https://youtube.com/@veritasium/videos",
            ChannelRef("https://www.youtube.com/@veritasium"),
        ),
        ("@veritasium", ChannelRef("https://www.youtube.com/@veritasium")),
        (
            "https://www.youtube.com/c/veritasium",
            ChannelRef("https://www.youtube.com/c/veritasium"),
        ),
        (
            "https://www.youtube.com/user/1veritasium",
            ChannelRef("https://www.youtube.com/user/1veritasium"),
        ),
    ],
)
def test_parse_youtube_url(url: str, expected: object) -> None:
    assert parse_youtube_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        "https://vimeo.com/123",
        "https://notyoutube.com/watch?v=jNQXAC9IVRw",
        "https://www.youtube.com/",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/watch",
        "https://youtu.be/",
        "https://www.youtube.com/channel/not-a-channel-id",
        "https://www.youtube.com/@veritasium/videos/extra",
        "https://www.youtube.com/feed/subscriptions",
        "https://www.youtube.com/results?search_query=cats",
    ],
)
def test_unsupported_urls(url: str) -> None:
    with pytest.raises(UnsupportedUrlError):
        parse_youtube_url(url)
