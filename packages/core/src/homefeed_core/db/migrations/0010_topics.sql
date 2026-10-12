-- Topic boosts (see homefeed_core.curation): a plain-language description, embedded, and
-- a slider weight in [-1, 1]. Videos similar to the description get
-- weight * max(0, cos_sim - 0.3) / 0.7 added to their score. With decay on, the weight
-- halves every 30 days since reaffirmed_at (set on creation, when the weight changes,
-- when decay is turned on and by an explicit reaffirm).
-- embedding is the description's unit-length vector as little-endian float32 (384 of
-- them), from embedding_model; it is recomputed when the description or model changes.
-- NOCASE keeps "Woodworking" and "woodworking" from being two topics, so the name can
-- key the topic's term in a feed item's score breakdown.

CREATE TABLE topics (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(trim(name)) > 0),
    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
    embedding BLOB NOT NULL,
    embedding_model TEXT NOT NULL,
    weight REAL NOT NULL CHECK (weight BETWEEN -1 AND 1),
    decay INTEGER NOT NULL DEFAULT 0 CHECK (decay IN (0, 1)),
    reaffirmed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
