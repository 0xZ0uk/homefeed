"""Replays the recorded yt-dlp responses in `fixtures/gateway/`.

Re-record with `uv run python scripts/record_gateway_fixtures.py` (uses the network).
"""

import json
import os
from pathlib import Path
from typing import Any

from homefeed_core.gateway.ytdlp import ExtractRequest, classify_error

# Opt-in tests against real YouTube; the network is blocked otherwise.
LIVE_TESTS = os.environ.get("HOMEFEED_LIVE_TESTS") == "1"

FIXTURES = Path(__file__).parent / "fixtures" / "gateway"


class Replay:
    """An `extract` function serving recorded responses, keyed by request."""

    def __init__(self) -> None:
        self.records: dict[ExtractRequest, dict[str, Any]] = {}
        for path in sorted(FIXTURES.glob("*.json")):
            record = json.loads(path.read_text())
            self.records[ExtractRequest(**record["request"])] = record
        self.requests: list[ExtractRequest] = []

    def __call__(self, request: ExtractRequest) -> dict[str, Any]:
        self.requests.append(request)
        record = self.records.get(request)
        if record is None:
            raise AssertionError(f"No recorded response for {request}")
        if "error" in record:
            raise classify_error(record["error"])
        return record["response"]
