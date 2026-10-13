from pathlib import Path

import pytest

from homefeed_core.link_extraction import (
    ExtractionFailedError,
    find_urls,
    links_from_feed,
    links_from_html,
    links_from_subreddit_json,
)

FIXTURES = Path(__file__).parent / "fixtures" / "external"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_subreddit_listing_links_in_post_order() -> None:
    extracted = links_from_subreddit_json(fixture("subreddit_hot.json"))

    assert extracted.title == "r/Documentaries"
    assert extracted.links == [
        # A self post contributes the URLs in its text, not its own permalink.
        "https://youtu.be/aaaaaaaaaaa?t=42",
        "https://example.com/blog/post",
        # Link posts: the link (entities unescaped, deduplicated) and the media embed.
        "https://www.youtube.com/watch?v=bbbbbbbbbbb&feature=share",
        "https://www.youtube.com/watch?v=bbbbbbbbbbb",
        "https://www.youtube.com/shorts/sssssssssss",
        "https://vimeo.com/123456789",
        "https://www.youtube.com/@deepdives",
    ]


@pytest.mark.parametrize(
    "body", [b"<html>blocked</html>", b'{"kind": "t3"}', b'{"kind": "Listing", "data": {}}']
)
def test_subreddit_rejects_anything_but_a_listing(body: bytes) -> None:
    with pytest.raises(ExtractionFailedError):
        links_from_subreddit_json(body)


def test_rss_links_from_items_descriptions_and_content() -> None:
    extracted = links_from_feed(fixture("feed_rss.xml"), "https://slowscience.example.org/feed")

    assert extracted.title == "Slow Science Weekly"
    assert extracted.links == [
        "https://slowscience.example.org/issues/12",
        "https://www.youtube.com/watch?v=ccccccccccc",
        "https://slowscience.example.org/about",
        "https://www.youtube-nocookie.com/embed/ddddddddddd?rel=0",
        "https://youtu.be/eeeeeeeeeee",
        "https://example.org/cover.jpg",
    ]


def test_atom_links_resolve_relative_hrefs() -> None:
    extracted = links_from_feed(fixture("feed_atom.xml"), "https://vlog.example.net/feed.atom")

    assert extracted.title == "A Video Blog"
    assert extracted.links == [
        "https://vlog.example.net/posts/watch-this",
        "https://m.youtube.com/watch?v=fffffffffff&t=1m30s",
    ]


@pytest.mark.parametrize("body", [b"not xml at all", b"<html><body>hi</body></html>"])
def test_feed_rejects_non_feeds(body: bytes) -> None:
    with pytest.raises(ExtractionFailedError):
        links_from_feed(body, "https://example.com/feed")


def test_html_links_anchors_iframes_and_bare_urls() -> None:
    extracted = links_from_html(fixture("link_page.html"), "https://lectures.example.com/best")

    assert extracted.title == "Best lectures of 2026"
    assert extracted.links == [
        "https://www.youtube.com/watch?v=ggggggggggg",
        "https://youtu.be/hhhhhhhhhhh",  # fragment dropped
        "https://lectures.example.com/lists/2025.html",  # relative to <base>
        "https://www.youtube.com/watch?v=iiiiiiiiiii",
        "https://www.youtube.com/playlist?list=PL0123456789abcdef",
        "https://www.youtube.com/embed/ggggggggggg",
    ]


def test_html_never_fails() -> None:
    assert links_from_html(b"\xff\xfe<<<a href=", "https://example.com").links == []


def test_find_urls_trims_punctuation_but_keeps_balanced_parentheses() -> None:
    assert find_urls(
        "See https://a.example/x. Or (https://b.example/y), "
        "https://en.wikipedia.org/wiki/Heat_(film) and **https://c.example/z**!"
    ) == [
        "https://a.example/x",
        "https://b.example/y",
        "https://en.wikipedia.org/wiki/Heat_(film)",
        "https://c.example/z",
    ]
