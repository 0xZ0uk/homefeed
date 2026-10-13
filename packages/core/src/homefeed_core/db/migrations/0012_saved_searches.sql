-- Saved searches (see homefeed_core.saved_searches): a YouTube search whose results
-- become candidates (source 'saved_search', source_detail = the query) on a schedule.
-- query is stored as entered (trimmed, inner whitespace collapsed). filters is the
-- search's non-default YouTube filters as canonical JSON ('{}' for a plain search), so
-- the same query with the same filters (query ignoring case) is saved once.
-- schedule: 'daily' or 'weekly' runs, or 'paused'. A search that never ran is due now.
-- last_error is the last run's failure, NULL after a success.

CREATE TABLE saved_searches (
    id INTEGER PRIMARY KEY,
    query TEXT NOT NULL COLLATE NOCASE CHECK (length(trim(query)) > 0),
    filters TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(filters)),
    schedule TEXT NOT NULL DEFAULT 'daily' CHECK (schedule IN ('daily', 'weekly', 'paused')),
    last_run_at TEXT,
    last_found_count INTEGER CHECK (last_found_count >= 0),
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (query, filters)
);
