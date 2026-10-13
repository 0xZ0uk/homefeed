-- Ratings move from the 30-grade tier list to a 1 to 10 score with one decimal (see
-- homefeed_core.scores). Each grade becomes the score with the same value on the line
-- from 1.0 (value -1) to 10.0 (value +1): F-- is 1.0, C is 4.7, B is 6.3, A is 7.8 and
-- S++ is 10.0. The value is then recomputed from the rounded score.

CREATE TABLE ratings_new (
    video_id TEXT PRIMARY KEY,  -- YouTube video id
    score REAL NOT NULL CHECK (score BETWEEN 1.0 AND 10.0),  -- one decimal
    value REAL NOT NULL CHECK (value BETWEEN -1.0 AND 1.0),  -- (score - 5.5) / 4.5
    rated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),   -- first rated
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))  -- last changed
);

INSERT INTO ratings_new (video_id, score, value, rated_at, updated_at)
SELECT video_id, score, (score - 5.5) / 4.5, rated_at, updated_at
FROM (SELECT *, round(5.5 + 4.5 * value, 1) AS score FROM ratings);

DROP TABLE ratings;
ALTER TABLE ratings_new RENAME TO ratings;
CREATE INDEX ratings_rated_at ON ratings (rated_at);
