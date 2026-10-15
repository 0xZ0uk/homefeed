"""The candidate pipeline: what runs in what order to fill and use the candidate pool.

The worker schedules these (see `homefeed_core.jobs`); the API's feed refresh triggers
the poll. The order is: poll due subscriptions, run the other candidate sources,
enrich, then the feed build ranks and composes. A failing step is logged and the rest
still run, so one broken source or feed never blocks the others.

The locks keep two callers in one process from doing the same work at once: the API's
feed refresh and a scheduled poll (or enrichment) can overlap when `RUN_WORKER_IN_API`
runs the jobs in the API process. Across processes the poller's per-channel backoff,
`ON CONFLICT DO NOTHING` dedupe and SQLite's busy timeout hold the line instead.
"""

import logging
import threading

from homefeed_core import candidates, enricher, feeds, poller
from homefeed_core.db import get_session_factory
from homefeed_core.external_sources import ExternalSourcesSource
from homefeed_core.gateway import FeedFetcher, create_gateway
from homefeed_core.tag_discovery import TagDiscoverySource

logger = logging.getLogger(__name__)

# The poll job and a feed build (or manual refresh) must not poll at the same time.
_poll_lock = threading.Lock()
# Likewise for the enrich job's and the feed build's enrichment.
_enrich_lock = threading.Lock()


def poll_subscriptions(*, fetch: FeedFetcher | None = None) -> None:
    """Fetch due subscription feeds and record new uploads as candidates."""
    with _poll_lock:
        new = poller.poll_due_channels(fetch=fetch)
    logger.info("Subscription poll found %d new candidates", len(new))


def generate_candidates() -> None:
    """Run the candidate sources other than subscriptions (related videos of top-tier
    ratings, due saved searches); a failing source is logged and skipped."""
    report = candidates.generate()
    for source, video_ids in report.new.items():
        logger.info("Candidate source %r found %d new candidates", source, len(video_ids))
    for source, error in report.failed.items():
        logger.warning("Candidate source %r failed: %s", source, error)


def gather_candidates() -> None:
    """Poll due subscriptions, then run the other candidate sources."""
    try:
        poll_subscriptions()
    except Exception:
        logger.exception("Polling subscriptions failed; running the other sources anyway")
    generate_candidates()


def enrich_candidates() -> None:
    """Compute features (metadata, transcript excerpt, embedding) for new candidates."""
    with _enrich_lock:
        report = enricher.enrich_candidates()
    logger.info(
        "Enriched %d candidates (%d up to date, %d failed)",
        len(report.enriched),
        len(report.cached),
        len(report.failed),
    )


def fetch_external_sources() -> None:
    """Fetch due external sources and record the YouTube videos they link to."""
    sessions = get_session_factory()
    source = ExternalSourcesSource(sessions, create_gateway(sessions))
    report = candidates.generate([source], sessions=sessions)
    for name, video_ids in report.new.items():
        logger.info("Candidate source %r found %d new candidates", name, len(video_ids))
    for name, error in report.failed.items():
        logger.warning("Candidate source %r failed: %s", name, error)


def discover_tag_videos() -> None:
    """Search YouTube for the subscribed tags that are due and record the new videos."""
    sessions = get_session_factory()
    source = TagDiscoverySource(sessions, create_gateway(sessions))
    report = candidates.generate([source], sessions=sessions)
    for name, video_ids in report.new.items():
        logger.info("Candidate source %r found %d new candidates", name, len(video_ids))
    for name, error in report.failed.items():
        logger.warning("Candidate source %r failed: %s", name, error)


def build_daily_feed() -> None:
    """Gather candidates (subscriptions, related videos), enrich them, then rank and
    compose today's feed (poll → candidates → enrich → rank → compose)."""
    feed = feeds.refresh_feed(poll=gather_candidates, enrich=enrich_candidates)
    logger.info("Built the feed for %s with %d items", feed.date, len(feed.items))
