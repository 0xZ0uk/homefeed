-- Channels hidden from Discover (see homefeed_core.channel_hides). `dismissed` only
-- removes the channel from the suggestions; `blocked` ("Don't show") also keeps all of
-- its videos out of the feed, like a muted channel. Subscribing to a channel clears its
-- hide; the row goes with its channel.
CREATE TABLE channel_hides (
    channel_id TEXT PRIMARY KEY REFERENCES channels (id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('dismissed', 'blocked')),
    hidden_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
