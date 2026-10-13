"""First-run onboarding: whether the user still has to be walked through setup.

Setup is needed on a fresh install: no subscriptions and the flag below unset. Finishing
or skipping it sets the flag (a JSON `true` under `COMPLETED_KEY` in the `settings`
table), so unsubscribing from everything later doesn't bring it back.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

COMPLETED_KEY = "onboarding_completed"


@dataclass(frozen=True)
class OnboardingStatus:
    completed: bool
    subscribed_channels: int
    needed: bool  # not completed and nothing subscribed


def get_status(session: Session) -> OnboardingStatus:
    value = session.execute(
        text("SELECT value FROM settings WHERE key = :key"), {"key": COMPLETED_KEY}
    ).scalar_one_or_none()
    completed = value == "true"
    subscribed = session.execute(text("SELECT count(*) FROM channel_prefs")).scalar_one()
    return OnboardingStatus(
        completed=completed,
        subscribed_channels=subscribed,
        needed=not completed and subscribed == 0,
    )


def complete(session: Session) -> OnboardingStatus:
    """Mark onboarding done (finished or skipped). Safe to repeat."""
    session.execute(
        text(
            """
            INSERT INTO settings (key, value) VALUES (:key, 'true')
            ON CONFLICT (key) DO UPDATE SET
                value = 'true',
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """
        ),
        {"key": COMPLETED_KEY},
    )
    return get_status(session)
