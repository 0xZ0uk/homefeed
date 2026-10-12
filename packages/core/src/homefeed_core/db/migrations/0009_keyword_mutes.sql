-- Muted keywords (see homefeed_core.curation): a video whose title or description
-- contains one, as a whole word or phrase and ignoring case, is filtered out of the feed.
-- keyword is stored as entered (trimmed, inner whitespace collapsed); NOCASE keeps
-- "Crypto" and "crypto" from being muted twice.

CREATE TABLE keyword_mutes (
    id INTEGER PRIMARY KEY,
    keyword TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(trim(keyword)) > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
