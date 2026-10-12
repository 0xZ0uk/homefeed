-- Timestamps are ISO 8601 UTC text, e.g. 2026-10-12T06:00:00.000Z.

CREATE TABLE channels (
    id TEXT PRIMARY KEY,  -- YouTube channel id (UC...)
    title TEXT NOT NULL,
    handle TEXT,          -- e.g. @somechannel
    url TEXT,
    thumbnail_url TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE videos (
    id TEXT PRIMARY KEY,  -- YouTube video id
    channel_id TEXT NOT NULL REFERENCES channels (id),
    title TEXT NOT NULL,
    description TEXT,
    duration_seconds INTEGER,
    published_at TEXT,
    thumbnail_url TEXT,
    -- not_live, is_live, is_upcoming, was_live, post_live
    live_status TEXT,
    is_short INTEGER NOT NULL DEFAULT 0 CHECK (is_short IN (0, 1)),
    view_count INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX videos_channel_published ON videos (channel_id, published_at);

-- User-editable app settings as JSON values, keyed by name.
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL CHECK (json_valid(value)),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
