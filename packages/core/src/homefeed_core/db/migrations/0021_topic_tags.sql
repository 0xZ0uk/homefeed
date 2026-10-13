-- Tag-backed topics (see homefeed_core.curation): subscribing to a tag creates a topic
-- linked to it, so the ranker can boost videos that carry the tag.
--
-- tag_id links the topic to a tag; NULL for a topic defined by its description alone.
-- A tag has at most one topic (the unique index; NULLs never collide). ON DELETE CASCADE:
-- a topic about a tag that no longer exists means nothing, so it goes with the tag. Merging
-- tags must therefore re-link the source tag's topic before deleting the tag (see
-- curation.relink_tag_topic).
--
-- match_mode says what counts as a match: 'embedding' (the description's similarity, as
-- before), 'tag' (the video carries the tag) or 'both' (the stronger of the two). 'tag' and
-- 'both' need a tag_id, which curation checks (SQLite cannot add a cross-column CHECK
-- with ALTER TABLE).
--
-- description and embedding stay NOT NULL (SQLite cannot relax a constraint in place): a
-- tag-backed topic without a description stores the tag's label as its description and
-- embeds that, so switching its mode to 'embedding' or 'both' always works.

ALTER TABLE topics ADD COLUMN tag_id INTEGER REFERENCES tags (id) ON DELETE CASCADE;
ALTER TABLE topics
    ADD COLUMN match_mode TEXT NOT NULL DEFAULT 'embedding'
    CHECK (match_mode IN ('embedding', 'tag', 'both'));

CREATE UNIQUE INDEX idx_topics_tag ON topics (tag_id);
