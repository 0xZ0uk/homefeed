from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import channel_hides
from homefeed_core.curation import (
    get_channel,
    list_channels,
    subscribe,
    unsubscribe,
    update_channel,
    upsert_channel,
)
from homefeed_core.db import open_database
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.gateway.fake import FakeGateway, make_channel
from homefeed_core.scores import score_value
from homefeed_core.trials import (
    TRIAL_DAYS,
    earned_keep,
    end_trial,
    keep_trial,
    settle_trials,
    start_trial,
)

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
END = NOW + timedelta(days=TRIAL_DAYS)
KEEPER = make_channel("UC" + "k" * 22, title="Keeper")
POOR = make_channel("UC" + "p" * 22, title="Poor")
IDLE = make_channel("UC" + "i" * 22, title="Idle")
PLAIN = make_channel("UC" + "n" * 22, title="Plain")
UNKNOWN = "UC" + "u" * 22


def stamp(at: datetime) -> str:
    return format_timestamp(at)


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    with factory.begin() as session:
        for channel in (KEEPER, POOR, IDLE, PLAIN):
            upsert_channel(session, channel)
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def rate(
    session: Session,
    video_id: str,
    channel_id: str,
    score: int,
    *,
    rated_at: datetime,
    updated_at: datetime | None = None,
) -> None:
    """A rating with the given times, on a video of the channel."""
    session.execute(
        text("INSERT OR IGNORE INTO videos (id, channel_id, title) VALUES (:id, :channel, 'v')"),
        {"id": video_id, "channel": channel_id},
    )
    session.execute(
        text(
            "INSERT INTO ratings (video_id, score, value, rated_at, updated_at) "
            "VALUES (:id, :score, :value, :rated, :updated)"
        ),
        {
            "id": video_id,
            "score": score,
            "value": score_value(score),
            "rated": stamp(rated_at),
            "updated": stamp(updated_at or rated_at),
        },
    )


def test_migration_adds_the_trial_and_timed_mute_columns(
    sessions: sessionmaker[Session],
) -> None:
    with sessions() as session:
        columns = session.execute(text("SELECT name FROM pragma_table_info('channel_prefs')"))
        names = [row[0] for row in columns]

    assert names[-2:] == ["trial_until", "muted_until"]


def test_start_trial_subscribes_with_an_end_time(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        started = start_trial(session, KEEPER.id, now=NOW)

    assert started is not None
    channel, created = started
    assert created is True
    assert channel.channel_id == KEEPER.id
    assert channel.trial_until == stamp(END)
    assert channel.subscribed_at == stamp(NOW)
    assert (channel.prior, channel.pinned, channel.muted) == ("neutral", False, False)
    with sessions() as session:
        assert [c.channel_id for c in list_channels(session)] == [KEEPER.id]


def test_a_trial_is_fourteen_days() -> None:
    assert TRIAL_DAYS == 14


def test_start_trial_needs_a_known_channel(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        assert start_trial(session, UNKNOWN, now=NOW) is None

    with sessions() as session:
        assert list_channels(session) == []


def test_starting_a_trial_clears_a_hide(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        channel_hides.hide(session, KEEPER.id, "blocked")

    with sessions.begin() as session:
        start_trial(session, KEEPER.id, now=NOW)

    with sessions() as session:
        assert channel_hides.get_hide(session, KEEPER.id) is None


def test_starting_a_trial_leaves_an_existing_subscription_alone(
    sessions: sessionmaker[Session], gateway_for_plain: FakeGateway
) -> None:
    with sessions.begin() as session:
        subscribe(session, gateway_for_plain, PLAIN.url or "")
        update_channel(session, PLAIN.id, prior="like")
        channel_hides.hide(session, PLAIN.id, "blocked")

    with sessions.begin() as session:
        started = start_trial(session, PLAIN.id, now=NOW)
        assert started is not None
        plain, created = started
        start_trial(session, KEEPER.id, now=NOW)
        again = start_trial(session, KEEPER.id, now=NOW + timedelta(days=3))
        assert again is not None
        running, running_created = again

    assert created is False
    assert (plain.trial_until, plain.prior) == (None, "like")
    with sessions() as session:
        # An existing subscription keeps its hide, like `subscribe` leaves its prefs.
        hide = channel_hides.get_hide(session, PLAIN.id)
        assert hide is not None and hide.kind == "blocked"
    assert running_created is False
    assert running.trial_until == stamp(END)  # not restarted


@pytest.fixture
def gateway_for_plain() -> FakeGateway:
    gateway = FakeGateway()
    gateway.add_channel(PLAIN)
    return gateway


def test_keep_trial_makes_a_plain_subscription(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        start_trial(session, KEEPER.id, now=NOW)
        update_channel(session, KEEPER.id, prior="love")

    with sessions.begin() as session:
        kept = keep_trial(session, KEEPER.id, now=NOW + timedelta(days=2))
        assert kept is not None
        assert (kept.trial_until, kept.prior) == (None, "love")
        assert kept.updated_at == stamp(NOW + timedelta(days=2))
        assert keep_trial(session, KEEPER.id, now=NOW) is None  # no longer on trial

    with sessions() as session:
        assert get_channel(session, KEEPER.id) == kept


def test_keep_trial_needs_a_trial(
    sessions: sessionmaker[Session], gateway_for_plain: FakeGateway
) -> None:
    with sessions.begin() as session:
        subscribe(session, gateway_for_plain, PLAIN.url or "")
        assert keep_trial(session, PLAIN.id, now=NOW) is None  # subscribed, not on trial
        assert keep_trial(session, IDLE.id, now=NOW) is None  # not subscribed


def test_end_trial_unsubscribes_and_records_not_now(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        start_trial(session, POOR.id, now=NOW)
        update_channel(session, POOR.id, prior="like")

    with sessions.begin() as session:
        assert end_trial(session, POOR.id) is True
        assert end_trial(session, POOR.id) is False

    with sessions() as session:
        assert get_channel(session, POOR.id) is None
        hide = channel_hides.get_hide(session, POOR.id)
        assert hide is not None and hide.kind == "dismissed"
        assert POOR.id not in channel_hides.blocked_channel_ids(session)


def test_end_trial_leaves_a_plain_subscription_alone(
    sessions: sessionmaker[Session], gateway_for_plain: FakeGateway
) -> None:
    with sessions.begin() as session:
        subscribe(session, gateway_for_plain, PLAIN.url or "")
        assert end_trial(session, PLAIN.id) is False
        assert end_trial(session, IDLE.id) is False

    with sessions() as session:
        assert get_channel(session, PLAIN.id) is not None
        assert channel_hides.list_hides(session) == []


def test_a_rating_counts_when_made_or_changed_during_the_trial(
    sessions: sessionmaker[Session],
) -> None:
    before = NOW - timedelta(days=1)
    during = NOW + timedelta(days=3)
    with sessions.begin() as session:
        rate(session, "kkkkkkkkkk1", KEEPER.id, 7, rated_at=during)
        rate(session, "ppppppppp01", POOR.id, 9, rated_at=before)
        rate(session, "ppppppppp02", POOR.id, 6, rated_at=during)
        rate(session, "iiiiiiiiii1", IDLE.id, 9, rated_at=before, updated_at=during)

    with sessions() as session:
        started = stamp(NOW)
        assert earned_keep(session, KEEPER.id, started) is True  # 7 is top tier
        assert earned_keep(session, POOR.id, started) is False  # 9 was before, 6 isn't top tier
        assert earned_keep(session, IDLE.id, started) is True  # rated before, changed during
        assert earned_keep(session, PLAIN.id, started) is False  # nothing rated


def test_settling_keeps_the_channels_that_earned_it_and_ends_the_rest(
    sessions: sessionmaker[Session], gateway_for_plain: FakeGateway
) -> None:
    with sessions.begin() as session:
        for channel in (KEEPER, POOR, IDLE):
            start_trial(session, channel.id, now=NOW)
        subscribe(session, gateway_for_plain, PLAIN.url or "")
        rate(session, "kkkkkkkkkk1", KEEPER.id, 8, rated_at=NOW + timedelta(days=5))
        rate(session, "ppppppppp01", POOR.id, 5, rated_at=NOW + timedelta(days=5))

    with sessions.begin() as session:
        report = settle_trials(session, now=END)

    assert report.kept == [KEEPER.id]
    assert report.ended == [IDLE.id, POOR.id]  # in channel id order: they ended together
    with sessions() as session:
        remaining = {c.channel_id: c for c in list_channels(session)}
        assert set(remaining) == {KEEPER.id, PLAIN.id}
        assert remaining[KEEPER.id].trial_until is None
        assert {h.channel_id: h.kind for h in channel_hides.list_hides(session)} == {
            IDLE.id: "dismissed",
            POOR.id: "dismissed",
        }


def test_settling_leaves_trials_that_have_not_run_out(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        start_trial(session, IDLE.id, now=NOW)
        start_trial(session, POOR.id, now=NOW + timedelta(days=2))

    with sessions.begin() as session:
        report = settle_trials(session, now=END + timedelta(hours=1))
        nothing = settle_trials(session, now=NOW + timedelta(days=13))

    assert (report.kept, report.ended) == ([], [IDLE.id])  # only IDLE's trial has run out
    assert (nothing.kept, nothing.ended) == ([], [])
    with sessions() as session:
        assert [c.channel_id for c in list_channels(session)] == [POOR.id]


def test_settling_twice_does_nothing_the_second_time(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        start_trial(session, IDLE.id, now=NOW)
        start_trial(session, KEEPER.id, now=NOW)
        rate(session, "kkkkkkkkkk1", KEEPER.id, 10, rated_at=NOW + timedelta(days=1))

    with sessions.begin() as session:
        first = settle_trials(session, now=END)
        second = settle_trials(session, now=END)

    assert (first.kept, first.ended) == ([KEEPER.id], [IDLE.id])
    assert (second.kept, second.ended) == ([], [])


def test_a_channel_that_was_subscribed_again_later_is_judged_from_its_new_trial(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        start_trial(session, KEEPER.id, now=NOW)
        rate(session, "kkkkkkkkkk1", KEEPER.id, 9, rated_at=NOW + timedelta(days=1))
        unsubscribe(session, KEEPER.id)
    later = NOW + timedelta(days=30)
    with sessions.begin() as session:
        start_trial(session, KEEPER.id, now=later)

    with sessions.begin() as session:
        report = settle_trials(session, now=later + timedelta(days=TRIAL_DAYS))

    assert report.ended == [KEEPER.id]  # the old rating is from before this trial
