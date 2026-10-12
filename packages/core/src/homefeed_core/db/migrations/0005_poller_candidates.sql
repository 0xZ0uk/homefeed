-- Subscription polling state and the candidate pool (see homefeed_core.poller and
-- homefeed_core.candidates).

-- Per-channel RSS poll schedule and backoff. A subscribed channel without a row has
-- never been polled and is due now. consecutive_failures drives exponential backoff
-- and resets on the next successful poll.
CREATE TABLE channel_polls (
    channel_id TEXT PRIMARY KEY REFERENCES channels (id) ON DELETE CASCADE,
    next_poll_at TEXT NOT NULL,
    last_polled_at TEXT,   -- last attempt, successful or not
    last_success_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    last_error TEXT        -- NULL after a success
);

CREATE INDEX channel_polls_next_poll_at ON channel_polls (next_poll_at);

-- Videos that may go into a feed, one row per (video, source) so each source's
-- attribution is kept. source is e.g. 'subscription'; source_detail says which one
-- (the channel id for subscriptions, the query for searches, ...).
CREATE TABLE candidates (
    video_id TEXT NOT NULL REFERENCES videos (id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_detail TEXT,
    first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (video_id, source)
);

CREATE INDEX candidates_first_seen_at ON candidates (first_seen_at);
