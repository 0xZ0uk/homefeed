-- Channel subscriptions and their curation preferences (see homefeed_core.curation).
-- A row means the channel is subscribed; unsubscribing deletes the row (the channel and
-- its videos stay in `channels` / `videos`). prior feeds the ranker's channel score
-- (love +0.8, like +0.4, neutral 0, skeptical -0.4); pinned channels' new uploads lead
-- the feed; muted channels are filtered out of it.

CREATE TABLE channel_prefs (
    channel_id TEXT PRIMARY KEY REFERENCES channels (id) ON DELETE CASCADE,
    prior TEXT NOT NULL DEFAULT 'neutral'
        CHECK (prior IN ('love', 'like', 'neutral', 'skeptical')),
    pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
    muted INTEGER NOT NULL DEFAULT 0 CHECK (muted IN (0, 1)),
    subscribed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
