"""A live smoke test of the Gateway against real YouTube, to catch breakage early.

It runs one small request per Gateway operation against long-lived, well-known videos
and channels and checks that the normalized answers still look right. Each request is
recorded in `extractor_events` like any other (when the Gateway records), and the run
itself is recorded as one `smoke_test` event, failed if any check failed, which the
status page reports (see `homefeed_core.extractor_status`).

It uses the network, so it never runs in tests or CI: the worker schedules it only when
`GATEWAY_SMOKE_TEST_TIME` is set, and it can be run by hand with

    uv run python -m homefeed_core.smoke_test
"""

import logging
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import get_session_factory
from homefeed_core.extractor_status import SMOKE_TEST_OPERATION
from homefeed_core.gateway import (
    EventRecorder,
    ExtractorEvent,
    FeedFetcher,
    Gateway,
    GatewayError,
    ResolvedChannel,
    SqlEventRecorder,
    create_feed_fetcher,
    create_gateway,
)

logger = logging.getLogger(__name__)

# "Me at the zoo", the first YouTube video: stable title, captions and formats.
ZOO_VIDEO = "jNQXAC9IVRw"
ZOO_TITLE = "Me at the zoo"
VERITASIUM = "UCHnyfMqiRRG1u-2MsSQLbXA"
VERITASIUM_URL = "https://www.youtube.com/@veritasium"
SEARCH_QUERY = "veritasium"
# Error messages are cut to this length in the summary event.
MAX_ERROR_LENGTH = 300


class SmokeCheckFailed(Exception):
    """A request succeeded but its answer doesn't look right."""

    kind = "unexpected_response"


@dataclass(frozen=True)
class SmokeCheck:
    name: str
    ok: bool
    duration_ms: int
    error_kind: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class SmokeTestReport:
    started_at: datetime
    duration_ms: int
    checks: list[SmokeCheck]

    @property
    def success(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def failed(self) -> list[SmokeCheck]:
        return [check for check in self.checks if not check.ok]

    def summary(self) -> str | None:
        """The failed checks and their errors, or None if all passed."""
        if self.success:
            return None
        return "; ".join(
            f"{check.name}: {(check.error or check.error_kind or 'failed')[:MAX_ERROR_LENGTH]}"
            for check in self.failed
        )


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeCheckFailed(message)


def _get_video(gateway: Gateway) -> None:
    video = gateway.get_video(ZOO_VIDEO)
    expect(video.title == ZOO_TITLE, f"unexpected title {video.title!r}")
    expect(bool(video.duration_seconds), "no duration")


def _get_formats(gateway: Gateway) -> None:
    formats = gateway.get_formats(ZOO_VIDEO)
    expect(any(f.kind == "audio" for f in formats), "no audio-only format")
    expect(any(f.kind == "video" for f in formats), "no video-only format")


def _get_captions(gateway: Gateway) -> None:
    captions = gateway.get_captions(ZOO_VIDEO)
    expect(captions is not None, "no captions")
    assert captions is not None
    expect("elephant" in captions.text().lower(), "captions don't mention elephants")


def _get_related(gateway: Gateway) -> None:
    expect(bool(gateway.get_related(ZOO_VIDEO, limit=5)), "no related videos")


def _get_comments(gateway: Gateway) -> None:
    expect(bool(gateway.get_comments(ZOO_VIDEO, limit=5)), "no comments")


def _search(gateway: Gateway) -> None:
    expect(bool(gateway.search(SEARCH_QUERY, limit=5)), "no search results")


def _get_channel_uploads(gateway: Gateway) -> None:
    uploads = gateway.get_channel_uploads(VERITASIUM, limit=3)
    expect(uploads.channel.id == VERITASIUM, f"unexpected channel {uploads.channel.id!r}")
    expect(bool(uploads.videos), "no uploads")


def _get_featured_channels(gateway: Gateway) -> None:
    expect(bool(gateway.get_featured_channels(VERITASIUM)), "no featured channels")


def _resolve_url(gateway: Gateway) -> None:
    resolved = gateway.resolve_url(VERITASIUM_URL)
    expect(
        isinstance(resolved, ResolvedChannel) and resolved.channel.id == VERITASIUM,
        f"resolved to {resolved!r}",
    )


type Check = tuple[str, Callable[[Gateway], None]]

GATEWAY_CHECKS: Sequence[Check] = (
    ("get_video", _get_video),
    ("get_formats", _get_formats),
    ("get_captions", _get_captions),
    ("get_related", _get_related),
    ("get_comments", _get_comments),
    ("search", _search),
    ("get_channel_uploads", _get_channel_uploads),
    ("get_featured_channels", _get_featured_channels),
    ("resolve_url", _resolve_url),
)


def _channel_feed(fetch_feed: FeedFetcher) -> None:
    body = fetch_feed(VERITASIUM)
    expect(b"<feed" in body and b"<yt:videoId>" in body, "not a channel feed with videos")


def run_smoke_test(
    gateway: Gateway,
    fetch_feed: FeedFetcher | None = None,
    *,
    recorder: EventRecorder | None = None,
    checks: Sequence[Check] = GATEWAY_CHECKS,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> SmokeTestReport:
    """Run every check (a failing one doesn't stop the others) and, with a `recorder`,
    record the run as one `smoke_test` event."""
    started_at = now()
    started = time.monotonic()
    results = [_run_check(name, lambda check=check: check(gateway)) for name, check in checks]
    if fetch_feed is not None:
        results.append(_run_check("get_channel_feed", lambda: _channel_feed(fetch_feed)))
    report = SmokeTestReport(
        started_at=started_at,
        duration_ms=round((time.monotonic() - started) * 1000),
        checks=results,
    )
    if recorder is not None:
        first_failure = next(iter(report.failed), None)
        recorder.record(
            ExtractorEvent(
                operation=SMOKE_TEST_OPERATION,
                target=None,
                success=report.success,
                at=started_at,
                duration_ms=report.duration_ms,
                error_kind=first_failure.error_kind if first_failure else None,
                error=report.summary(),
            )
        )
    return report


def _run_check(name: str, check: Callable[[], None]) -> SmokeCheck:
    started = time.monotonic()
    error_kind: str | None = None
    error: str | None = None
    try:
        check()
    except (GatewayError, SmokeCheckFailed) as failure:
        error_kind, error = failure.kind, str(failure)
    except Exception as failure:
        error_kind, error = "unexpected_error", repr(failure)
    duration_ms = round((time.monotonic() - started) * 1000)
    if error is not None:
        logger.warning("Smoke check %s failed (%s): %s", name, error_kind, error)
    return SmokeCheck(
        name=name, ok=error is None, duration_ms=duration_ms, error_kind=error_kind, error=error
    )


def run_live_smoke_test(sessions: sessionmaker[Session] | None = None) -> SmokeTestReport:
    """The smoke test through the production Gateway and feed fetcher, recorded in the
    database. Uses the network."""
    sessions = sessions or get_session_factory()
    return run_smoke_test(
        create_gateway(sessions),
        create_feed_fetcher(sessions),
        recorder=SqlEventRecorder(sessions),
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    report = run_live_smoke_test()
    for check in report.checks:
        status = "ok" if check.ok else f"FAILED ({check.error_kind}): {check.error}"
        print(f"{check.name}: {status} [{check.duration_ms} ms]")
    print("Smoke test passed" if report.success else "Smoke test failed")
    return 0 if report.success else 1


if __name__ == "__main__":
    sys.exit(main())
