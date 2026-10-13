-- The watch queue (see homefeed_core.queue): videos to watch next, in order. Each video
-- is queued at most once. position is the 0-based place in the queue; homefeed_core.queue
-- keeps positions dense (0..n-1) on every add, move and removal.
-- video_id has no foreign key to videos, like ratings: the API stores a video's metadata
-- when it's queued, but the queue doesn't depend on it.

CREATE TABLE queue_items (
    id INTEGER PRIMARY KEY,
    video_id TEXT NOT NULL UNIQUE,  -- YouTube video id
    position INTEGER NOT NULL CHECK (position >= 0),
    added_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX queue_items_position ON queue_items (position);
