import logging
import signal
from types import FrameType

from apscheduler.schedulers.blocking import BlockingScheduler

from homefeed_core.config import get_settings

logger = logging.getLogger(__name__)


def build_scheduler() -> BlockingScheduler:
    """Create the scheduler with all worker jobs registered (none yet)."""
    return BlockingScheduler()


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    scheduler = build_scheduler()

    def stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("Received %s, shutting down", signal.Signals(signum).name)
        scheduler.shutdown()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    logger.info("Worker starting (database: %s)", settings.database_path)
    scheduler.start()
    logger.info("Worker stopped")
