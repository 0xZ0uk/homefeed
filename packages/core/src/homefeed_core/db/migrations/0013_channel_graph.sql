-- The channel graph (see homefeed_core.channel_graph): which channels feature which on
-- their page, as last fetched through the Gateway. Featured channels are upserted into
-- `channels` so they can be suggested and subscribed to.

-- One row per channel whose featured channels were fetched, even when it features none,
-- so the graph knows what is fresh. fetched_at is the last successful fetch.
CREATE TABLE channel_graph_fetches (
    channel_id TEXT PRIMARY KEY REFERENCES channels (id) ON DELETE CASCADE,
    fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- channel_id features featured_id, at position (0-based, the page's order).
-- subscriber_count is YouTube's rounded count for featured_id when fetched.
CREATE TABLE featured_channels (
    channel_id TEXT NOT NULL REFERENCES channel_graph_fetches (channel_id) ON DELETE CASCADE,
    featured_id TEXT NOT NULL REFERENCES channels (id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    subscriber_count INTEGER CHECK (subscriber_count IS NULL OR subscriber_count >= 0),
    PRIMARY KEY (channel_id, featured_id)
);

CREATE INDEX featured_channels_featured_id ON featured_channels (featured_id);
