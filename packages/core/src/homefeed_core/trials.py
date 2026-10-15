"""Trial subscriptions: try a channel for two weeks before committing to it.

"Try for 2 weeks" (`start_trial`) subscribes to a channel the way `curation.subscribe`
does, except that the subscription carries `trial_until`, `TRIAL_DAYS` ahead. The daily
worker job (`settle_trials`) then looks at every trial that has run out:

- If a video of the channel was rated top tier (7 and up) since the trial began, counting
  a rating made or changed in that time, the channel earned its place: the trial flag is
  cleared and the subscription goes on like any other (`keep_trial`).
- Otherwise the trial ends (`end_trial`): the channel is unsubscribed by the same
  function as any unsubscribe (`curation.unsubscribe`) and recorded as hidden with kind
  `dismissed`, which the app words as "Not now", so Discover doesn't suggest it again
  right away.

Keeping and ending are also done by hand, any time during the trial ("Keep", "End
trial"). The trial starts when the subscription is made (`subscribed_at`).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_core import channel_hides, curation
from homefeed_core.curation import SubscribedChannel
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.scores import TOP_TIER_THRESHOLD

# How long a trial lasts, in days.
TRIAL_DAYS = 14


@dataclass(frozen=True)
class TrialReport:
    """What `settle_trials` did, as channel ids."""

    kept: list[str]
    ended: list[str]


def start_trial(
    session: Session, channel_id: str, *, now: datetime | None = None
) -> tuple[SubscribedChannel, bool] | None:
    """Subscribe to a channel on a trial of `TRIAL_DAYS`. Returns the subscription and
    whether it is new, or `None` if the channel isn't known (it must be in `channels`:
    featured by a channel, or fetched with the channel page).

    A new subscription clears any hide of the channel, as `curation.subscribe` does. A
    channel that is already subscribed, on trial or not, is left as it is: starting a
    trial never turns a plain subscription into one that can end by itself, nor restarts
    a running trial."""
    known = session.execute(
        text("SELECT 1 FROM channels WHERE id = :id"), {"id": channel_id}
    ).first()
    if known is None:
        return None
    now = now or datetime.now(UTC)
    inserted = session.execute(
        text(
            """
            INSERT INTO channel_prefs (channel_id, trial_until, subscribed_at, updated_at)
            VALUES (:id, :until, :now, :now)
            ON CONFLICT (channel_id) DO NOTHING
            RETURNING channel_id
            """
        ),
        {
            "id": channel_id,
            "until": format_timestamp(now + timedelta(days=TRIAL_DAYS)),
            "now": format_timestamp(now),
        },
    ).first()
    if inserted is not None:
        session.execute(
            text("DELETE FROM channel_hides WHERE channel_id = :id"), {"id": channel_id}
        )
    subscription = curation.get_channel(session, channel_id, now=now)
    assert subscription is not None
    return subscription, inserted is not None


def keep_trial(
    session: Session, channel_id: str, *, now: datetime | None = None
) -> SubscribedChannel | None:
    """Make a trial a plain subscription. Returns it, or `None` if the channel isn't on
    trial (not subscribed, or subscribed without a trial)."""
    now = now or datetime.now(UTC)
    kept = session.execute(
        text(
            """
            UPDATE channel_prefs SET trial_until = NULL, updated_at = :now
            WHERE channel_id = :id AND trial_until IS NOT NULL
            RETURNING channel_id
            """
        ),
        {"id": channel_id, "now": format_timestamp(now)},
    ).first()
    return None if kept is None else curation.get_channel(session, channel_id, now=now)


def end_trial(session: Session, channel_id: str) -> bool:
    """End a trial: unsubscribe, and record the channel as hidden with kind `dismissed`
    ("Not now") so it isn't suggested again right away. Returns whether the channel was
    on trial; a channel that isn't is left alone."""
    on_trial = session.execute(
        text("SELECT 1 FROM channel_prefs WHERE channel_id = :id AND trial_until IS NOT NULL"),
        {"id": channel_id},
    ).first()
    if on_trial is None:
        return False
    curation.unsubscribe(session, channel_id)
    channel_hides.hide(session, channel_id, "dismissed")
    return True


def earned_keep(session: Session, channel_id: str, since: str) -> bool:
    """Whether a video of the channel was rated top tier at or after `since` (ISO 8601
    UTC). A rating changed since then counts, one made earlier and left alone doesn't."""
    return bool(
        session.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM ratings AS r JOIN videos AS v ON v.id = r.video_id
                    WHERE v.channel_id = :id AND r.score >= :threshold AND r.updated_at >= :since
                )
                """
            ),
            {"id": channel_id, "threshold": TOP_TIER_THRESHOLD, "since": since},
        ).scalar_one()
    )


def settle_trials(session: Session, *, now: datetime | None = None) -> TrialReport:
    """Decide every trial that has run out (`trial_until` at or before `now`): keep the
    channel if it earned a top-tier rating during the trial, else end the trial. The
    caller commits."""
    now = now or datetime.now(UTC)
    due = session.execute(
        text(
            """
            SELECT channel_id, subscribed_at FROM channel_prefs
            WHERE trial_until IS NOT NULL AND trial_until <= :now
            ORDER BY trial_until, channel_id
            """
        ),
        {"now": format_timestamp(now)},
    ).all()
    report = TrialReport(kept=[], ended=[])
    for channel_id, started in due:
        if earned_keep(session, channel_id, started):
            keep_trial(session, channel_id, now=now)
            report.kept.append(channel_id)
        else:
            end_trial(session, channel_id)
            report.ended.append(channel_id)
    return report
