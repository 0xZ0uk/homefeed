-- External sources (see homefeed_core.external_sources): subreddits, RSS/Atom feeds and
-- link pages whose YouTube links become candidates (source 'external').
--
-- url is canonical for its kind (a subreddit is stored as https://www.reddit.com/r/name);
-- title is what the source calls itself, filled in by the first successful fetch.
-- Each source is fetched again `schedule` after a success; failures back off
-- exponentially (consecutive_failures), never waiting longer than the schedule.

CREATE TABLE external_sources (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('subreddit', 'rss', 'page')),
    url TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(url) > 0),
    title TEXT,
    schedule TEXT NOT NULL DEFAULT 'daily' CHECK (schedule IN ('hourly', 'daily', 'weekly')),
    next_fetch_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_fetched_at TEXT,  -- last attempt, successful or not
    last_success_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    last_error TEXT,       -- NULL after a success
    last_found_count INTEGER,  -- YouTube videos found by the last successful fetch
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX external_sources_next_fetch_at ON external_sources (next_fetch_at);
