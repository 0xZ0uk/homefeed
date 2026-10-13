-- Hard-hide a muted tag (see homefeed_core.curation): with hide set, videos that carry the
-- topic's tag are dropped from the feed instead of only ranked down, like keyword mutes.
--
-- Only meaningful for a tag-backed topic at stored weight -1; curation enforces that
-- (SQLite cannot add a cross-column CHECK with ALTER TABLE) and clears hide whenever the
-- weight changes away from -1.

ALTER TABLE topics ADD COLUMN hide INTEGER NOT NULL DEFAULT 0 CHECK (hide IN (0, 1));
