"""Finding links in what external sources serve: subreddit listings, RSS/Atom feeds and
HTML pages. Pure parsing, no network.

Every extractor returns `ExtractedLinks`: the source's own title (when it has one) and
the absolute http(s) links it contains, deduplicated in order of first appearance. It
doesn't judge the links; deciding which point at YouTube videos is the Gateway's job
(`Gateway.resolve_url`).
"""

import html
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit


class ExtractionFailedError(ValueError):
    """The content isn't what its kind promised (not a subreddit listing, not a feed)."""


@dataclass(frozen=True)
class ExtractedLinks:
    title: str | None
    links: list[str] = field(default_factory=list[str])


# A bare URL in text or markdown; trailing punctuation is trimmed afterwards.
_BARE_URL = re.compile(r"""https?://[^\s<>"'`\[\]{}|\\^]+""", re.IGNORECASE)
_TRAILING = ".,;:!?*_~'\")"


def find_urls(text: str) -> list[str]:
    """Bare http(s) URLs in plain text or markdown, in order."""
    urls: list[str] = []
    for match in _BARE_URL.finditer(text):
        url = match.group(0)
        # Strip trailing punctuation, keeping a ")" that closes a "(" in the URL.
        while url and url[-1] in _TRAILING:
            if url[-1] == ")" and url.count("(") >= url.count(")"):
                break
            url = url[:-1]
        urls.append(url)
    return urls


# Subreddits (Reddit's `/r/<name>/<listing>.json`)


def links_from_subreddit_json(body: bytes) -> ExtractedLinks:
    """Links of a subreddit listing: each post's link, its media embed and any URLs in
    its text. Raises `ExtractionFailedError` if `body` isn't a listing."""
    try:
        data = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExtractionFailedError(f"Not JSON: {error}") from error
    if not isinstance(data, dict) or data.get("kind") != "Listing":
        raise ExtractionFailedError("Not a subreddit listing")
    children = _get(data, "data", "children")
    if not isinstance(children, list):
        raise ExtractionFailedError("Listing has no posts array")
    links: list[str] = []
    title: str | None = None
    for child in children:
        post = _get(child, "data")
        if not isinstance(post, dict):
            continue
        if title is None and isinstance(post.get("subreddit_name_prefixed"), str):
            title = post["subreddit_name_prefixed"]
        if post.get("is_self") is not True:
            for key in ("url_overridden_by_dest", "url"):
                value = post.get(key)
                if isinstance(value, str):
                    links.append(html.unescape(value))
        for media_key in ("secure_media", "media"):
            embed_url = _get(post, media_key, "oembed", "url")
            if isinstance(embed_url, str):
                links.append(html.unescape(embed_url))
        selftext = post.get("selftext")
        if isinstance(selftext, str):
            links += find_urls(html.unescape(selftext))
    return ExtractedLinks(title, _clean(links))


def _get(value: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)  # pyright: ignore[reportUnknownMemberType]
    return value  # pyright: ignore[reportUnknownVariableType]


# RSS 2.0 and Atom feeds

_ATOM = "{http://www.w3.org/2005/Atom}"
_MEDIA = "{http://search.yahoo.com/mrss/}"
_CONTENT_ENCODED = "{http://purl.org/rss/1.0/modules/content/}encoded"


def links_from_feed(body: bytes, base_url: str) -> ExtractedLinks:
    """Links of an RSS 2.0 or Atom feed: each item's link, enclosures and media, and the
    links and URLs in its description or content (HTML). Raises `ExtractionFailedError`
    for anything else."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise ExtractionFailedError(f"Not XML: {error}") from error
    if root.tag == f"{_ATOM}feed":
        title = _child_text(root, f"{_ATOM}title")
        items = root.findall(f"{_ATOM}entry")
    elif root.tag == "rss" or root.tag.endswith("}RDF"):
        channel = root.find("channel")
        title = _child_text(channel, "title") if channel is not None else None
        # RSS 1.0 (RDF) puts items next to the channel rather than in it.
        items = root.findall("channel/item") + [
            node for node in root if node.tag.endswith("}item") or node.tag == "item"
        ]
    else:
        raise ExtractionFailedError(f"Not an RSS or Atom feed (root element {root.tag!r})")

    links: list[str] = []
    for item in items:
        for node in item.iter():
            tag = node.tag if isinstance(node.tag, str) else ""
            if tag == f"{_ATOM}link" and node.get("href"):
                links.append(urljoin(base_url, node.get("href", "")))
            elif tag.endswith("}link") or tag == "link":
                if node.text and node.text.strip():
                    links.append(urljoin(base_url, node.text.strip()))
            elif tag in ("enclosure", f"{_MEDIA}content", f"{_MEDIA}player"):
                url = node.get("url")
                if url:
                    links.append(urljoin(base_url, url))
            elif tag in (
                "description",
                _CONTENT_ENCODED,
                f"{_ATOM}content",
                f"{_ATOM}summary",
                f"{_MEDIA}description",
            ) or tag.endswith("}description"):
                if node.text:
                    links += links_from_html(node.text, base_url).links
    return ExtractedLinks(title, _clean(links))


def _child_text(node: ET.Element | None, tag: str) -> str | None:
    if node is None:
        return None
    child = node.find(tag)
    text = (child.text or "").strip() if child is not None else ""
    return " ".join(text.split()) or None


# HTML pages

_LINK_ATTRIBUTES = {"a": "href", "iframe": "src", "embed": "src", "area": "href"}


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.base: str | None = None
        self.title_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0  # inside <script> or <style>

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "base" and values.get("href") and self.base is None:
            self.base = values["href"]
        elif tag == "title":
            self._in_title = True
        elif tag in ("script", "style"):
            self._skip_depth += 1
        attribute = _LINK_ATTRIBUTES.get(tag)
        if attribute and values.get(attribute):
            self.links.append(values[attribute] or "")
        if tag == "object" and values.get("data"):
            self.links.append(values["data"] or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        elif not self._skip_depth:
            self.links += find_urls(data)


def links_from_html(body: bytes | str, base_url: str) -> ExtractedLinks:
    """Links of an HTML page or fragment: anchors, iframes and embeds (relative ones
    resolved against the page) and bare URLs in its text. Never fails; garbage in gives
    no links."""
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    parser = _LinkParser()
    try:
        parser.feed(text)
        parser.close()
    except AssertionError:  # HTMLParser's way of giving up on malformed markup
        pass
    base = urljoin(base_url, parser.base) if parser.base else base_url
    title = " ".join("".join(parser.title_parts).split()) or None
    links: list[str] = []
    for link in parser.links:
        try:
            links.append(urljoin(base, link.strip()))
        except ValueError:
            continue
    return ExtractedLinks(title, _clean(links))


def _clean(links: Iterable[str]) -> list[str]:
    """Absolute http(s) links, without fragments, deduplicated in order."""
    seen: dict[str, None] = {}
    for link in links:
        link = link.strip()
        try:
            parts = urlsplit(link)
        except ValueError:
            continue
        if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
            continue
        seen.setdefault(parts._replace(fragment="").geturl(), None)
    return list(seen)
