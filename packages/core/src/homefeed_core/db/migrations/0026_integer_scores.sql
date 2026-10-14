-- Ratings move from a 1 to 10 score with one decimal to a whole score, 1 to 10 (see
-- homefeed_core.scores). Existing scores are rounded to the nearest whole score, halves
-- up (SQLite's round() rounds half away from zero, so 5.5 is 6 and 6.5 is 7). The value
-- is then recomputed from the whole score. Rating times stay as they were.

CREATE TABLE ratings_new (
    video_id TEXT PRIMARY KEY,  -- YouTube video id
    score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 10),  -- whole score
    value REAL NOT NULL CHECK (value BETWEEN -1.0 AND 1.0),  -- (score - 5.5) / 4.5
    rated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),   -- first rated
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))  -- last changed
);

INSERT INTO ratings_new (video_id, score, value, rated_at, updated_at)
SELECT video_id, whole_score, (whole_score - 5.5) / 4.5, rated_at, updated_at
FROM (SELECT *, CAST(round(score) AS INTEGER) AS whole_score FROM ratings);

DROP TABLE ratings;
ALTER TABLE ratings_new RENAME TO ratings;
CREATE INDEX ratings_rated_at ON ratings (rated_at);
