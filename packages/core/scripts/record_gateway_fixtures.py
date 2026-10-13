"""Record the yt-dlp responses that the Gateway tests replay. Uses the network.

    uv run python scripts/record_gateway_fixtures.py

Each fixture is `{"request": ..., "response": ...}` or `{"request": ..., "error": ...}`
in `tests/fixtures/gateway/`. Bulky fields the Gateway ignores are dropped and the
client IP embedded in stream URLs is replaced with a documentation address. Caption
tracks keep only the first `CAPTION_SECONDS` and the json3 fields the Gateway reads.
"""

import json
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from homefeed_core.gateway.errors import GatewayError
from homefeed_core.gateway.models import SearchFilters
from homefeed_core.gateway.ytdlp import ExtractRequest, extract_info, search_url

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures" / "gateway"

VERITASIUM = "UCHnyfMqiRRG1u-2MsSQLbXA"

SEARCH_LIMIT = 5
COMMENTS_LIMIT = 5
SEARCH_FILTERS = SearchFilters(sort="upload_date", upload_date="month", duration="long")


def search_request(query: str, filters: SearchFilters | None = None) -> ExtractRequest:
    return ExtractRequest(search_url(query, filters, SEARCH_LIMIT), flat=True, limit=SEARCH_LIMIT)


REQUESTS: dict[str, ExtractRequest] = {
    "video_me_at_the_zoo": ExtractRequest("https://www.youtube.com/watch?v=jNQXAC9IVRw"),
    "video_long": ExtractRequest("https://www.youtube.com/watch?v=NiCgcUTL9_Q"),
    "video_short": ExtractRequest("https://www.youtube.com/watch?v=j9p3Sn8ROL4"),
    "video_unavailable": ExtractRequest("https://www.youtube.com/watch?v=xxxxxxxxxxx"),
    "channel_uploads": ExtractRequest(
        f"https://www.youtube.com/channel/{VERITASIUM}/videos", flat=True, limit=5
    ),
    "channel_missing": ExtractRequest(
        "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx/videos", flat=True, limit=5
    ),
    "resolve_handle": ExtractRequest(
        "https://www.youtube.com/@veritasium/videos", flat=True, limit=1
    ),
    "resolve_user": ExtractRequest(
        "https://www.youtube.com/user/1veritasium/videos", flat=True, limit=1
    ),
    # Uploaded English captions.
    "captions_me_at_the_zoo": ExtractRequest(
        "https://www.youtube.com/watch?v=jNQXAC9IVRw", captions=True
    ),
    "captions_long": ExtractRequest("https://www.youtube.com/watch?v=NiCgcUTL9_Q", captions=True),
    # Automatic captions only.
    "captions_automatic": ExtractRequest(
        "https://www.youtube.com/watch?v=j9p3Sn8ROL4", captions=True
    ),
    # No captions at all.
    "captions_none": ExtractRequest("https://www.youtube.com/watch?v=hY7m5jjJ9mM", captions=True),
    "captions_unavailable": ExtractRequest(
        "https://www.youtube.com/watch?v=xxxxxxxxxxx", captions=True
    ),
    # The watch page's related list (InnerTube `next`).
    "related_long": ExtractRequest("https://www.youtube.com/watch?v=NiCgcUTL9_Q", related=True),
    "related_me_at_the_zoo": ExtractRequest(
        "https://www.youtube.com/watch?v=jNQXAC9IVRw", related=True
    ),
    "related_unavailable": ExtractRequest(
        "https://www.youtube.com/watch?v=xxxxxxxxxxx", related=True
    ),
    # Search: plain (`ytsearchN:`), filtered (results page with `sp`), and no results.
    "search_hand_planes": search_request("woodworking hand planes"),
    "search_filtered": search_request("woodworking", SEARCH_FILTERS),
    "search_no_results": search_request("qxzvbnmplkjh wrtpsdfgh zzqqxx"),
    # Featured channels from the home tab (InnerTube `browse`).
    "featured_veritasium": ExtractRequest(
        f"https://www.youtube.com/channel/{VERITASIUM}", featured=True
    ),
    # Lists one channel twice.
    "featured_jawed": ExtractRequest(
        "https://www.youtube.com/channel/UC4QobU6STFB0P71PMvOGN5A", featured=True
    ),
    # Features no channels (Veritasium en Français).
    "featured_none": ExtractRequest(
        "https://www.youtube.com/channel/UCin0m13qWv3-051xlWlHamA", featured=True
    ),
    "featured_missing": ExtractRequest(
        "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx", featured=True
    ),
    # Top comments (pinned first, replies left out).
    "comments_me_at_the_zoo": ExtractRequest(
        "https://www.youtube.com/watch?v=jNQXAC9IVRw", limit=COMMENTS_LIMIT, comments=True
    ),
    "comments_unavailable": ExtractRequest(
        "https://www.youtube.com/watch?v=xxxxxxxxxxx", limit=COMMENTS_LIMIT, comments=True
    ),
}

CAPTION_SECONDS = 600
CAPTION_EVENT_KEYS = {"tStartMs", "dDurationMs", "segs"}

DROP_KEYS = {
    "automatic_captions",
    "subtitles",
    "requested_subtitles",
    "requested_formats",
    "heatmap",
    "fragments",
    "_version",
}
IP_PATTERNS = [
    (re.compile(r"([?&]ip=)[^&]+"), r"\g<1>203.0.113.1"),
    (re.compile(r"(/ip/)[^/]+"), r"\g<1>203.0.113.1"),
]


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in DROP_KEYS}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        for pattern, replacement in IP_PATTERNS:
            value = pattern.sub(replacement, value)
    return value


def trim_captions(response: dict[str, Any]) -> dict[str, Any]:
    captions = response.get("captions")
    if not captions:
        return response
    events: list[dict[str, Any]] = []
    for event in captions["events"]:
        if event.get("tStartMs", 0) >= CAPTION_SECONDS * 1000:
            continue
        trimmed = {k: v for k, v in event.items() if k in CAPTION_EVENT_KEYS}
        if "segs" in trimmed:
            trimmed["segs"] = [{"utf8": seg.get("utf8", "")} for seg in trimmed["segs"]]
        events.append(trimmed)
    return {**response, "captions": {**captions, "events": events}}


def main(names: list[str]) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, request in REQUESTS.items():
        if names and name not in names:
            continue
        record: dict[str, Any] = {"request": asdict(request)}
        try:
            record["response"] = trim_captions(scrub(extract_info(request)))
        except GatewayError as error:
            record["error"] = str(error)
        path = FIXTURES / f"{name}.json"
        path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n")
        print(f"{path.name}: {'error' if 'error' in record else 'ok'}")


if __name__ == "__main__":
    main(sys.argv[1:])
