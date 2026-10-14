-- Tags supersede topics (see homefeed_core.curation): a subscription to a tag is now its
-- own row, and the topics table (0010, 0021, 0022) goes.
--
-- tag_subscriptions holds the tags the user follows or mutes, one row per tag, with a
-- slider weight in [-1, 1]: positive boosts videos carrying the tag (subscribed), negative
-- suppresses them (muted). hide drops those videos from the feed instead; only at weight
-- -1, which curation enforces and clears whenever the weight changes away from -1 (the
-- CHECK keeps the stored data consistent with that). The row goes with its tag.
--
-- What carries over from topics:
-- - every tag-backed topic, with its stored weight and hide. Topic decay is gone: a
--   decaying topic keeps its stored (undecayed) weight. Match modes are gone too: a
--   subscription matches videos carrying the tag.
-- - a topic without a tag whose name, lowercased with spaces as hyphens, is the slug or an
--   alias of a tag that has no subscription yet, and whose weight is not 0. Other topics
--   without a tag (matched by their description's embedding) have no tag to become, and
--   are dropped with the table.

CREATE TABLE tag_subscriptions (
    tag_id INTEGER PRIMARY KEY REFERENCES tags (id) ON DELETE CASCADE,
    weight REAL NOT NULL CHECK (weight BETWEEN -1 AND 1),
    hide INTEGER NOT NULL DEFAULT 0 CHECK (hide IN (0, 1) AND (hide = 0 OR weight = -1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

INSERT INTO tag_subscriptions (tag_id, weight, hide, created_at, updated_at)
SELECT p.tag_id, p.weight, CASE WHEN p.hide = 1 AND p.weight = -1 THEN 1 ELSE 0 END,
       p.created_at, p.updated_at
FROM topics AS p JOIN tags AS t ON t.id = p.tag_id
ORDER BY p.id;

INSERT OR IGNORE INTO tag_subscriptions (tag_id, weight, hide, created_at, updated_at)
SELECT coalesce(t.id, a.tag_id), p.weight, 0, p.created_at, p.updated_at
FROM topics AS p
LEFT JOIN tags AS t ON t.slug = lower(replace(trim(p.name), ' ', '-'))
LEFT JOIN tag_aliases AS a ON a.alias = lower(replace(trim(p.name), ' ', '-'))
WHERE p.tag_id IS NULL AND p.weight != 0 AND coalesce(t.id, a.tag_id) IS NOT NULL
ORDER BY p.id;

DROP TABLE topics;
