-- One row per Gateway operation that reached YouTube (successful or not), for the
-- status page and for spotting extractor breakage.
CREATE TABLE extractor_events (
    id INTEGER PRIMARY KEY,
    operation TEXT NOT NULL,  -- get_video, get_formats, get_channel_uploads, resolve_url
    target TEXT,              -- the video id, channel id or URL asked for
    success INTEGER NOT NULL CHECK (success IN (0, 1)),
    error_kind TEXT,          -- unavailable, rate_limited, extraction, ...; NULL on success
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 1 CHECK (attempts >= 1),
    duration_ms INTEGER,
    at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX extractor_events_operation_at ON extractor_events (operation, at);
CREATE INDEX extractor_events_failures_at ON extractor_events (at) WHERE success = 0;
