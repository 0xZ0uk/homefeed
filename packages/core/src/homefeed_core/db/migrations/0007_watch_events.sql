-- Watch events from the player (see homefeed_core.watch_events): what happened, where in
-- the video, and when. A video counts as watched once it has a 'play' event; abandonment
-- within 60 seconds is derived from these rows.
-- video_id has no foreign key to videos, like ratings: events are recorded as reported.

CREATE TABLE watch_events (
    id INTEGER PRIMARY KEY,
    video_id TEXT NOT NULL,  -- YouTube video id
    event_type TEXT NOT NULL CHECK (event_type IN ('play', 'pause', 'seeked', 'ended', 'close')),
    position REAL NOT NULL CHECK (position >= 0),     -- seconds into the video
    duration REAL CHECK (duration IS NULL OR duration > 0),  -- seconds; NULL while unknown
    at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))  -- when it was recorded
);

CREATE INDEX watch_events_video_id_at ON watch_events (video_id, at);
CREATE INDEX watch_events_played ON watch_events (video_id) WHERE event_type = 'play';
