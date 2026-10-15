-- Trial subscriptions and timed mutes on subscribed channels (see homefeed_core.trials and
-- homefeed_core.curation).
--
-- trial_until: set when a channel is subscribed as a trial ("Try for 2 weeks"); the trial
-- ends at this time. The daily trial job then keeps the subscription (and clears this) if
-- a video of the channel was rated top tier since the trial began, and otherwise
-- unsubscribes and records a "Not now" hide. NULL: a plain subscription.
--
-- muted_until: set by "Mute for a month": the channel counts as muted until this time and
-- then comes back by itself, with nothing to undo. Apart from `muted`, the permanent mute.
-- NULL: not muted for a time.
--
-- Both are ISO 8601 UTC text like every timestamp, e.g. 2026-10-12T06:00:00.000Z.

ALTER TABLE channel_prefs ADD COLUMN trial_until TEXT;
ALTER TABLE channel_prefs ADD COLUMN muted_until TEXT;
