-- Embeddings of tag labels (see homefeed_core.tags), so a proposed tag close in meaning to
-- an existing one resolves to it. embedding is the little-endian float32 vector of the
-- label (like topics.embedding) and embedding_model the model that made it. Both are NULL
-- for a tag not embedded yet: it takes no part in matching until the worker's
-- refresh_tag_embeddings embeds it (as it does after an EMBEDDING_MODEL change).

ALTER TABLE tags ADD COLUMN embedding BLOB;
ALTER TABLE tags ADD COLUMN embedding_model TEXT;
