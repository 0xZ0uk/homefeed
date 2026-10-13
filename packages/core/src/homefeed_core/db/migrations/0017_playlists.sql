-- Local playlists (see homefeed_core.playlists): named, ordered lists of videos kept
-- only in this app. Names are unique ignoring case.
-- playlist_items.video_id deliberately has no foreign key to videos: a video can be
-- added (like a rating) before its metadata has been stored; listings show what is known.
-- position is 0-based and kept contiguous per playlist by the application.

CREATE TABLE playlists (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(trim(name)) > 0),
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE playlist_items (
    playlist_id INTEGER NOT NULL REFERENCES playlists (id) ON DELETE CASCADE,
    video_id TEXT NOT NULL,  -- YouTube video id
    position INTEGER NOT NULL CHECK (position >= 0),
    added_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (playlist_id, video_id)
);

CREATE INDEX playlist_items_position ON playlist_items (playlist_id, position);
CREATE INDEX playlist_items_video ON playlist_items (video_id);
