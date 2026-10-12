-- Daily feeds and their items (see homefeed_core.feeds).
-- A date can have several feeds: a manual refresh adds a new one rather than replacing
-- the old, so dismissals and what was shown stay on record. The feed for a date is the
-- latest one created for it.

CREATE TABLE feeds (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,        -- local calendar date the feed is for, YYYY-MM-DD
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    model_version TEXT         -- NULL while ranking is rules-only (no trained model)
);

CREATE INDEX feeds_date_created_at ON feeds (date, created_at);

-- breakdown is the ranker's score breakdown as JSON:
-- {"model": m, "alpha": a, "channel": c, "topics": {name: t, ...}, "final": f}
-- with alpha * model + channel + sum(topics) = final (= score).
CREATE TABLE feed_items (
    id INTEGER PRIMARY KEY,
    feed_id INTEGER NOT NULL REFERENCES feeds (id) ON DELETE CASCADE,
    video_id TEXT NOT NULL REFERENCES videos (id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),  -- 0-based order in the feed
    source TEXT NOT NULL,      -- candidate source, e.g. 'subscription'
    source_detail TEXT,
    score REAL NOT NULL,
    breakdown TEXT NOT NULL CHECK (json_valid(breakdown)),
    explanation TEXT NOT NULL,
    is_pinned INTEGER NOT NULL DEFAULT 0 CHECK (is_pinned IN (0, 1)),
    is_exploration INTEGER NOT NULL DEFAULT 0 CHECK (is_exploration IN (0, 1)),
    -- Probability the item was picked; only set for exploration items (Milestone 3).
    selection_probability REAL CHECK (selection_probability BETWEEN 0.0 AND 1.0),
    dismissed_at TEXT,
    dismiss_reason TEXT,
    UNIQUE (feed_id, position),
    UNIQUE (feed_id, video_id)
);

CREATE INDEX feed_items_video_id ON feed_items (video_id);
CREATE INDEX feed_items_dismissed ON feed_items (video_id) WHERE dismissed_at IS NOT NULL;
