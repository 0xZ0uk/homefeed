from homefeed_worker.scheduler import build_scheduler


def test_build_scheduler_has_no_jobs() -> None:
    scheduler = build_scheduler()

    assert scheduler.get_jobs() == []
    assert not scheduler.running
