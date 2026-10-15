-- "More like this" and "Less like this" on videos (see homefeed_core.feedback): a quick
-- steer given from a feed card, without rating the video. signal is 1 (more) or -1 (less),
-- one per video; pressing the same one again clears it by deleting the row.
--
-- Feedback is not a rating. It is not counted for the model's weight, the insights or
-- training; it only moves the ranker's similarity term, which treats a video that has
-- feedback and no rating like a top-tier (more) or bottom-tier (less) rated one. An
-- explicit rating always wins. The row goes with its video.

CREATE TABLE video_feedback (
    video_id TEXT PRIMARY KEY REFERENCES videos (id) ON DELETE CASCADE,
    signal INTEGER NOT NULL CHECK (signal IN (-1, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),  -- first given
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))   -- last changed
);
