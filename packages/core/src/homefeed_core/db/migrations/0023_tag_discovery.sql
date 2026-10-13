-- Tag discovery state (see homefeed_core.tag_discovery): when each subscribed tag was
-- last searched on YouTube, so a tag is searched once a day. The row goes with its tag
-- (unsubscribing keeps it, which only delays the next search after resubscribing).
CREATE TABLE tag_discovery_runs (
    tag_id INTEGER PRIMARY KEY REFERENCES tags (id) ON DELETE CASCADE,
    last_run_at TEXT NOT NULL,   -- last attempt, successful or not
    last_found_count INTEGER,    -- results found by the last successful run
    last_error TEXT              -- why the last run failed; NULL after a success
);
