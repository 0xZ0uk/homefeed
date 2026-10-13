-- LLM tags per video (see homefeed_core.llm_tags): a broad topic, how in-depth the
-- video is, and how clickbait-y and rage-bait-y it is, each score in [0, 1]. Cached
-- per video and prompt version: bumping llm_tags.TAG_PROMPT_VERSION retags every video
-- on its next enrichment, and only tags of the current version are used as features.
-- model names the provider and model that produced them, e.g.
-- 'openrouter:google/gemini-2.5-flash-lite'; changing the model alone doesn't retag.

CREATE TABLE video_llm_tags (
    video_id TEXT NOT NULL REFERENCES videos (id) ON DELETE CASCADE,
    prompt_version INTEGER NOT NULL,
    model TEXT NOT NULL,
    topic TEXT NOT NULL,
    depth REAL NOT NULL CHECK (depth BETWEEN 0.0 AND 1.0),
    clickbait REAL NOT NULL CHECK (clickbait BETWEEN 0.0 AND 1.0),
    rage_bait REAL NOT NULL CHECK (rage_bait BETWEEN 0.0 AND 1.0),
    tagged_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (video_id, prompt_version)
);
