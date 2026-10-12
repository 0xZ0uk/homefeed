-- Explicit tier-list ratings, one per video (see homefeed_core.grades).
-- video_id deliberately has no foreign key to videos: a video can be rated (e.g. from
-- search or a pasted URL) before its metadata has been stored.

CREATE TABLE ratings (
    video_id TEXT PRIMARY KEY,  -- YouTube video id
    grade TEXT NOT NULL CHECK (grade IN (
        'F--', 'F-', 'F', 'F+', 'F++',
        'D--', 'D-', 'D', 'D+', 'D++',
        'C--', 'C-', 'C', 'C+', 'C++',
        'B--', 'B-', 'B', 'B+', 'B++',
        'A--', 'A-', 'A', 'A+', 'A++',
        'S--', 'S-', 'S', 'S+', 'S++'
    )),
    value REAL NOT NULL CHECK (value BETWEEN -1.0 AND 1.0),  -- -1 + 2 * index / 29
    rated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),   -- first rated
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))  -- last changed
);

CREATE INDEX ratings_rated_at ON ratings (rated_at);
