"""Record the yt-dlp responses that the Gateway tests replay. Uses the network.

    uv run python scripts/record_gateway_fixtures.py

Each fixture is `{"request": ..., "response": ...}` or `{"request": ..., "error": ...}`
in `tests/fixtures/gateway/`. Bulky fields the Gateway ignores are dropped and the
client IP embedded in stream URLs is replaced with a documentation address.
"""

import json
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from homefeed_core.gateway.errors import GatewayError
from homefeed_core.gateway.ytdlp import ExtractRequest, extract_info

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures" / "gateway"

VERITASIUM = "UCHnyfMqiRRG1u-2MsSQLbXA"

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
}

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


def main(names: list[str]) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, request in REQUESTS.items():
        if names and name not in names:
            continue
        record: dict[str, Any] = {"request": asdict(request)}
        try:
            record["response"] = scrub(extract_info(request))
        except GatewayError as error:
            record["error"] = str(error)
        path = FIXTURES / f"{name}.json"
        path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n")
        print(f"{path.name}: {'error' if 'error' in record else 'ok'}")


if __name__ == "__main__":
    main(sys.argv[1:])
