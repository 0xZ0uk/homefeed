-- Specific tags for videos (see homefeed_core.tags), e.g. `rust`, `woodworking`, `f1`,
-- next to the broad LLM topic in video_llm_tags.
--
-- tags is the canonical vocabulary: slug is the normalized, unique key (lowercase words
-- joined by hyphens, see tags.slugify) and label is how it is shown.
--
-- tag_aliases maps other spellings, as slugs, to a canonical tag, so a proposed
-- `rust-lang` can resolve to `rust`. An alias is never also a tag slug (the application
-- checks the slug first). source says who made it: 'auto' (the resolver matched a
-- spelling to an existing tag) or 'user' (a merge or rename by hand), which wins over
-- automatic matching.
--
-- video_tags links videos to tags. source is 'llm' (proposed by the tagger, with the
-- model's confidence and the prompt_version it came from) or 'manual' (added by hand,
-- confidence 1, no prompt version). removed_at marks a link the user removed: the row
-- stays as a tombstone so re-tagging doesn't add it again, and readers skip it.

CREATE TABLE tags (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE CHECK (length(slug) > 0),
    label TEXT NOT NULL CHECK (length(trim(label)) > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE tag_aliases (
    alias TEXT PRIMARY KEY CHECK (length(alias) > 0),  -- a slug
    tag_id INTEGER NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('auto', 'user')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX tag_aliases_tag ON tag_aliases (tag_id);

CREATE TABLE video_tags (
    video_id TEXT NOT NULL REFERENCES videos (id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('llm', 'manual')),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
    prompt_version INTEGER,  -- llm_tags.TAG_PROMPT_VERSION for 'llm'; NULL for 'manual'
    tagged_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    removed_at TEXT,  -- set when removed by hand: a tombstone
    PRIMARY KEY (video_id, tag_id)
);

CREATE INDEX video_tags_tag ON video_tags (tag_id, video_id);
