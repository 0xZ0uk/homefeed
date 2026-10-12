-- Trained ranking models (see homefeed_core.trainer and homefeed_core.ranking_models).
-- The nightly trainer records every model it trains, promoted or not, and keeps the
-- newest 10 (plus the active one) so an earlier version can be reactivated.
-- AUTOINCREMENT keeps ids of pruned versions from being reused, so a feed's
-- model_version (the id as text) always names the model that ranked it.
-- path is the model file relative to DATA_DIR. spearman and mae are measured on the
-- holdout (the newest 20% of explicit ratings by time); spearman is NULL when it is
-- undefined (constant predictions or labels). metrics holds those and the rest of the
-- training report as JSON. At most one version is active.

CREATE TABLE model_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('lightgbm', 'ridge')),
    feature_version INTEGER NOT NULL,  -- homefeed_core.model_features.FEATURE_VERSION
    spearman REAL CHECK (spearman IS NULL OR spearman BETWEEN -1.0 AND 1.0),
    mae REAL NOT NULL CHECK (mae >= 0),
    metrics TEXT NOT NULL CHECK (json_valid(metrics)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1)),
    activated_at TEXT  -- last time it became the active model; NULL if never
);

CREATE UNIQUE INDEX model_versions_one_active ON model_versions (active) WHERE active = 1;
