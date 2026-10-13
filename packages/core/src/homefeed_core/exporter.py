"""Full JSON export of the user's data (`GET /export`).

The export is one JSON object: a header (`format`, `version`, `schema_version`,
`exported_at`) followed by the data, grouped by area:

- `ratings`: every tier-list rating, with the video's title and channel when known.
- `curation`: subscribed channels with their prefs, topics, keyword mutes, saved
  searches and external sources.
- `feeds`: every feed built, with its items (score breakdown, explanation, dismissals).
- `library`: the watch history (every watch event), the watch queue and local playlists
  (each with its videos in order).
- `models`: trained ranking model versions and their metrics (not the model files).
- `settings`: the `settings` table (`stored`) and the runtime configuration from the
  environment (`config`), without secrets or file paths.

What goes in is the `SECTIONS` registry: each `ExportSection` names where its data goes
(a key path such as `("curation", "topics")`) and how to read it from the database. To
export something new, write a reader and add one `ExportSection` line. Everything is read
in the caller's transaction, so the export is a consistent snapshot.

Derived and cached data is left out (embeddings, enrichment features, LLM tags, the
candidate pool, poll state, extractor events): it is recomputed from YouTube as needed.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_core import curation, external_sources, ranking_models, saved_searches
from homefeed_core.config import get_settings
from homefeed_core.gateway.events import format_timestamp

EXPORT_FORMAT = "homefeed-export"
# Bump when the export's shape changes incompatibly (renamed or removed keys). Adding
# sections or fields doesn't need a bump.
EXPORT_VERSION = 1

# Configuration fields left out of `settings.config`: secrets and host file paths.
_PRIVATE_CONFIG = frozenset({"openrouter_api_key", "data_dir", "database_path"})

type Reader = Callable[[Session], Any]


@dataclass(frozen=True)
class ExportSection:
    path: tuple[str, ...]  # where the data goes, e.g. ("curation", "topics")
    read: Reader  # returns JSON-serializable data


def _rows(sql: str, *, json_columns: Sequence[str] = (), bool_columns: Sequence[str] = ()):
    """A reader returning each row of `sql` as a dict keyed by column name.

    `json_columns` hold JSON text and are decoded; `bool_columns` are 0/1 flags.
    """

    def read(session: Session) -> list[dict[str, Any]]:
        rows = [dict(row) for row in session.execute(text(sql)).mappings()]
        for row in rows:
            for column in json_columns:
                if row[column] is not None:
                    row[column] = json.loads(row[column])
            for column in bool_columns:
                row[column] = bool(row[column])
        return rows

    return read


def _dataclasses(list_all: Callable[[Session], Sequence[Any]]) -> Reader:
    """A reader returning `list_all(session)`'s dataclasses as dicts."""
    return lambda session: [asdict(item) for item in list_all(session)]


def _feeds(session: Session) -> list[dict[str, Any]]:
    """Every feed, oldest first, each with its items in feed order."""
    feeds = _rows("SELECT id, date, created_at, model_version FROM feeds ORDER BY created_at, id")(
        session
    )
    items = _rows(
        """
        SELECT i.feed_id, i.id, i.position, i.video_id, v.title, v.channel_id,
               c.title AS channel_title, i.source, i.source_detail, i.score, i.breakdown,
               i.explanation, i.is_pinned, i.is_exploration, i.selection_probability,
               i.dismissed_at, i.dismiss_reason
        FROM feed_items AS i
        LEFT JOIN videos AS v ON v.id = i.video_id
        LEFT JOIN channels AS c ON c.id = v.channel_id
        ORDER BY i.feed_id, i.position
        """,
        json_columns=["breakdown"],
        bool_columns=["is_pinned", "is_exploration"],
    )(session)
    by_feed: dict[int, list[dict[str, Any]]] = {feed["id"]: [] for feed in feeds}
    for item in items:
        by_feed[item.pop("feed_id")].append(item)
    return [{**feed, "items": by_feed[feed["id"]]} for feed in feeds]


def _playlists(session: Session) -> list[dict[str, Any]]:
    """Every playlist, by name, each with its videos in playlist order."""
    playlists = _rows(
        "SELECT id, name, description, created_at, updated_at FROM playlists ORDER BY name, id"
    )(session)
    items = _rows(
        """
        SELECT i.playlist_id, i.video_id, v.title, i.position, i.added_at
        FROM playlist_items AS i LEFT JOIN videos AS v ON v.id = i.video_id
        ORDER BY i.playlist_id, i.position
        """
    )(session)
    by_playlist: dict[int, list[dict[str, Any]]] = {p["id"]: [] for p in playlists}
    for item in items:
        by_playlist[item.pop("playlist_id")].append(item)
    return [{**p, "items": by_playlist[p["id"]]} for p in playlists]


def _stored_settings(session: Session) -> dict[str, Any]:
    rows = session.execute(text("SELECT key, value FROM settings ORDER BY key"))
    return {key: json.loads(value) for key, value in rows}


def _config(_session: Session) -> dict[str, Any]:
    return get_settings().model_dump(mode="json", exclude=set(_PRIVATE_CONFIG))


def _model_versions(session: Session) -> list[dict[str, Any]]:
    return [
        {**asdict(version), "compatible": version.compatible}
        for version in ranking_models.list_model_versions(session)
    ]


SECTIONS: list[ExportSection] = [
    ExportSection(
        ("ratings",),
        _rows(
            """
            SELECT r.video_id, r.grade, r.value, r.rated_at, r.updated_at,
                   v.title, v.channel_id, c.title AS channel_title
            FROM ratings AS r
            LEFT JOIN videos AS v ON v.id = r.video_id
            LEFT JOIN channels AS c ON c.id = v.channel_id
            ORDER BY r.rated_at, r.video_id
            """
        ),
    ),
    ExportSection(("curation", "channels"), _dataclasses(curation.list_channels)),
    ExportSection(("curation", "topics"), _dataclasses(curation.list_topics)),
    ExportSection(("curation", "keyword_mutes"), _dataclasses(curation.list_keyword_mutes)),
    ExportSection(("curation", "saved_searches"), _dataclasses(saved_searches.list_saved_searches)),
    ExportSection(("curation", "external_sources"), _dataclasses(external_sources.list_sources)),
    ExportSection(("feeds",), _feeds),
    ExportSection(
        ("library", "watch_events"),
        _rows(
            """
            SELECT e.id, e.video_id, v.title, e.event_type, e.position, e.duration, e.at
            FROM watch_events AS e LEFT JOIN videos AS v ON v.id = e.video_id
            ORDER BY e.at, e.id
            """
        ),
    ),
    ExportSection(
        ("library", "queue"),
        _rows(
            """
            SELECT q.video_id, v.title, q.position, q.added_at
            FROM queue_items AS q LEFT JOIN videos AS v ON v.id = q.video_id
            ORDER BY q.position
            """
        ),
    ),
    ExportSection(("library", "playlists"), _playlists),
    ExportSection(("models",), _model_versions),
    ExportSection(("settings", "stored"), _stored_settings),
    ExportSection(("settings", "config"), _config),
]


def export_data(
    session: Session,
    *,
    sections: Sequence[ExportSection] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Everything in `sections` (default: `SECTIONS`) as one JSON-serializable dict."""
    schema_version = session.execute(text("SELECT max(version) FROM schema_migrations")).scalar()
    data: dict[str, Any] = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "schema_version": schema_version,
        "exported_at": format_timestamp(now or datetime.now(UTC)),
    }
    for section in SECTIONS if sections is None else sections:
        *parents, key = section.path
        target = data
        for parent in parents:
            target = target.setdefault(parent, {})
        target[key] = section.read(session)
    return data
