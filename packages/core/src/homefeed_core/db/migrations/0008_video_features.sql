-- Content features per video (see homefeed_core.enricher), computed once and reused
-- until the embedding model or the enricher's prompt version changes.
-- tags are the uploader's YouTube tags. transcript_excerpt is the first ~5 minutes of
-- captions; transcript_status says why it is NULL ('missing': the video has no
-- captions, 'failed': fetching them failed).

CREATE TABLE video_features (
    video_id TEXT PRIMARY KEY REFERENCES videos (id) ON DELETE CASCADE,
    tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags)),  -- JSON array of strings
    transcript_excerpt TEXT,
    transcript_language TEXT,  -- caption track language, e.g. 'en' or 'en-orig'
    transcript_status TEXT NOT NULL CHECK (transcript_status IN ('ok', 'missing', 'failed')),
    embedding_model TEXT NOT NULL,      -- e.g. 'BAAI/bge-small-en-v1.5'
    prompt_version INTEGER NOT NULL,    -- version of the text recipe that was embedded
    enriched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- One embedding per video (sqlite-vec), unit length, written with video_features. A
-- model with another dimension needs a new table. Virtual tables can't have foreign
-- keys; rows are replaced by deleting and inserting (vec0 has no upsert).
CREATE VIRTUAL TABLE video_embeddings USING vec0(
    video_id TEXT PRIMARY KEY,
    embedding float[384] distance_metric=cosine
);
