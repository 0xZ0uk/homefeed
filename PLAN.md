# PLAN.md: Homefeed, a personal YouTube client with a learned home feed

This plan is written for Claude Code. It starts from a freshly created Turborepo (`create-turbo`) and builds the system in milestones. Work one milestone at a time, keep tests green, and stop for review at the end of each milestone.

## 1. What we're building

A self-hosted, single-user YouTube client. The centerpiece is a **finite daily home feed** ranked by a model trained on my explicit 1 to 10 ratings, blended with hand curation. It does not use the official YouTube Data API.

The feed is designed against compulsion: a fixed number of items, refreshed once a day, no autoplay, no infinite scroll, no "up next", and a "why this is here" explanation on every item.

Success metric: the **weekly good rate**, meaning the share of rated videos scored 5.5 or higher. Not watch time.

### Non-goals

- Multiple users, sharing, or public internet exposure (home network or VPN only).
- Signing in to YouTube, syncing with a Google account, or any write action on YouTube.
- The official YouTube Data API.
- Offline downloads, native apps, live streams in the feed.

## 2. Ground rules for implementation

1. **All YouTube access goes through the Gateway module** (`packages/core`, `gateway/`). No other module may import yt-dlp, call InnerTube, or fetch youtube.com / googlevideo.com URLs.
2. **Prefer yt-dlp for everything first** (metadata, streams, captions, related videos, search via `ytsearchN:`, channel tabs). Add a direct InnerTube client only where yt-dlp can't do the job, and keep it behind the Gateway interface.
3. **Deep modules, small interfaces.** Each module in section 5 has a narrow public interface. Tests target that interface only.
4. **Pure where possible.** The Ranker and Feed Composer are pure functions of their inputs (plus an injected random generator). No I/O inside them.
5. **Check current docs** for TanStack Start, Turborepo, nub, uv, yt-dlp, and sqlite-vec before scaffolding; their CLIs and APIs change. Pin versions in lockfiles. The JS package manager is **nub** (`nub install`, `nub add`, `nub run`); there is no pnpm. Workspace dependencies use `"*"` versions, as in the create-turbo template.
6. **Ask before deviating** from a decision in this file. Record any agreed change back into this file.

## 3. Rating scale

Ratings are scores from **1 to 10 with one decimal**, e.g. 4.2, 6.7 or 9.9 (91 possible scores). They replaced an earlier 30-grade tier list (S to F with ++/+/-/-- modifiers); migration `0018_rating_scores` converted each grade to the score with the same value (F-- = 1.0, C = 4.7, B = 6.3, A = 7.8, S++ = 10.0).

| Concept | Definition |
| --- | --- |
| Range | 1.0 to 10.0, in steps of 0.1 |
| Numeric value | `value = (score - 5.5) / 4.5` (1.0 = −1.0, 5.5 = 0, 10.0 = +1.0) |
| Good | 5.5 or higher |
| Top tier (liked set) | 7.0 or higher |
| Bottom tier (disliked set) | 4.0 or lower |

The thresholds keep every converted grade in the set it was in before (B-- = 5.7 is good, A-- = 7.2 is top tier, D++ = 3.8 is bottom tier).

Rating UX: when a video ends or the player is closed, show a slider from 💩 (1) to 🔥 (10) on a red-to-green track, with the exact score in a tooltip over the thumb, and a "Save 7.4" button. Arrow keys move 0.1, Page Up/Down a whole point. The prompt is always skippable, and ratings are editable later.

## 4. Stack and repo layout

### Stack

- **Monorepo:** Turborepo + nub workspaces (the `workspaces` field in the root `package.json`) for orchestration; **uv workspace** for Python.
- **Backend:** Python 3.12+, FastAPI (API process), APScheduler (worker process).
- **Storage:** SQLite (WAL mode) + sqlite-vec for embedding similarity. One database file shared by API and worker.
- **YouTube:** yt-dlp as a library; channel RSS feeds (`https://www.youtube.com/feeds/videos.xml?channel_id=…`) for subscriptions.
- **ML:** 384-dim embeddings from OpenRouter (`perplexity/pplx-embed-v1-0.6b`, `EMBEDDING_PROVIDER=openrouter`) or a local sentence-transformers model (`BAAI/bge-small-en-v1.5`), with similarity thresholds calibrated per model; LightGBM regressor, with logistic/ridge regression fallback while labels are few.
- **LLM tagging:** pluggable provider interface (`LLM_PROVIDER`): the hosted **OpenRouter** API by default (OpenAI-compatible chat completions at `https://openrouter.ai/api/v1`, key in `OPENROUTER_API_KEY`; tagging is skipped while no key is set), local Ollama as the alternative, or `none`. Added in Milestone 4.
- **Frontend:** TanStack Start (React, SSR), TanStack Router, TanStack Query, Tailwind. Server functions call the Python API, so the API is never exposed to the browser.
- **Player:** Shaka Player.
- **Python tooling:** uv, ruff, pyright, pytest.
- **JS tooling:** TypeScript strict, Playwright for a few E2E flows.
- **Deployment:** Docker Compose with `web`, `api`, `worker` services and a shared data volume.

### Target layout

```
apps/
  web/            # TanStack Start frontend          (@homefeed/web)
  api/            # FastAPI app, thin HTTP layer     (@homefeed/api)
  worker/         # APScheduler jobs, thin layer     (@homefeed/worker)
packages/
  core/           # Python domain logic, see section 5 (@homefeed/core)
  api-client/     # TS client generated from OpenAPI  (@homefeed/api-client)
  typescript-config/   # keep from create-turbo
  eslint-config/       # keep from create-turbo
pyproject.toml    # uv workspace root
uv.lock
turbo.json
nub.lock
docker-compose.yml
.env.example
PLAN.md
```

Python packages: `homefeed_core` (in `packages/core`), `homefeed_api` (in `apps/api`), `homefeed_worker` (in `apps/worker`). `api` and `worker` depend on `core` through the uv workspace. All domain logic lives in `core`; `api` and `worker` are thin entry points.

## 5. Milestone 0: monorepo setup

Goal: `nub run dev` starts web, api, and worker; `nub run test` and `nub run lint` run across all packages; the frontend imports a generated, typed API client.

### Tasks

1. **Clean up the create-turbo template.** Remove the Next.js `apps/web` and `apps/docs` and `packages/ui`. Keep `packages/typescript-config` and `packages/eslint-config`.
2. **Scaffold TanStack Start** into `apps/web` with the current official CLI. Add TanStack Query and Tailwind. Name it `@homefeed/web`.
3. **Create the uv workspace.** Root `pyproject.toml`:

   ```toml
   [tool.uv.workspace]
   members = ["apps/api", "apps/worker", "packages/core"]
   ```

   Each member has its own `pyproject.toml` with a `src/` layout. `api` and `worker` declare `homefeed-core` as a dependency with `[tool.uv.sources] homefeed-core = { workspace = true }`.
4. **Wrap each Python package in a `package.json`** so Turborepo can run it, and declare the core dependency so it's in Turbo's graph:

   ```json
   {
     "name": "@homefeed/api",
     "private": true,
     "scripts": {
       "dev": "uv run fastapi dev src/homefeed_api/main.py --port 8000",
       "test": "uv run pytest",
       "lint": "uv run ruff check . && uv run ruff format --check . && uv run pyright",
       "openapi": "uv run python -m homefeed_api.export_openapi"
     },
     "dependencies": { "@homefeed/core": "*" }
   }
   ```

   Same pattern for `@homefeed/worker` (`dev`: `uv run python -m homefeed_worker`) and `@homefeed/core` (`test`, `lint` only).
5. **Generated API client.** `packages/api-client` runs `@hey-api/openapi-ts` (or `openapi-typescript`) on `apps/api/openapi.json` and outputs to `src/generated/`. It lists `@homefeed/api` as a devDependency so Turbo knows the edge. `apps/web` depends on `@homefeed/api-client` Both `openapi.json` and `src/generated/` are gitignored build outputs. FastAPI uses the handler name as the operation id, so the client exposes e.g. `health()`. `api-client` pins its own TypeScript 6 because openapi-ts uses the TypeScript compiler API, which TypeScript 7 doesn't provide.
6. **turbo.json:** (as built; inputs outside a package use `$TURBO_ROOT$`, and `API_URL` is declared because Turbo runs in strict env mode)

   ```json
   {
     "$schema": "https://turborepo.dev/schema.json",
     "globalDependencies": ["pyproject.toml", "uv.lock"],
     "tasks": {
       "openapi": { "inputs": ["src/**", "$TURBO_ROOT$/packages/core/src/**"], "outputs": ["openapi.json"] },
       "generate": { "dependsOn": ["@homefeed/api#openapi"], "outputs": ["src/generated/**"] },
       "build": { "dependsOn": ["^build", "^generate"], "outputs": [".output/**", "dist/**"], "env": ["API_URL"] },
       "dev": { "dependsOn": ["^generate"], "env": ["API_URL"], "persistent": true, "cache": false },
       "test": { "dependsOn": ["^generate"] },
       "lint": { "dependsOn": ["^generate"] },
       "check-types": { "dependsOn": ["^generate"] }
     }
   }
   ```

7. **Ignore files.** `.venv/`, `__pycache__/`, `*.sqlite*`, `data/`, `.env` in `.gitignore` (Turbo hashes git-tracked files).
8. **Config.** `.env.example` with `DATA_DIR`, `DATABASE_PATH`, `API_URL` (used by web server functions), `APP_PASSWORD`, `SESSION_SECRET`, `FEED_SIZE=20`, `FEED_REFRESH_TIME=06:00`, `LLM_PROVIDER=none`. Load Python config with pydantic-settings.
9. **Smoke check.** API exposes `GET /health`; the web home page calls it through a server function using the generated client and shows the result.

### Acceptance

- `nub run dev` runs all three processes; editing a Pydantic response model and re-running `generate` produces a TypeScript error where the frontend uses the changed field.
- `nub run test` and `nub run lint` pass from the root.

## 6. Architecture

```
TanStack Start web app ──server functions──▶ API process (FastAPI)
                                              │  Playback Service, Curation, Ratings/Library
                                              ▼
                                   packages/core (shared) ◀── Worker process (APScheduler)
                                   ├─ SQLite + sqlite-vec       Poller → Candidates → Enricher
                                   └─ YouTube Gateway ──▶ YouTube   → Ranker → Feed Composer; Trainer (nightly)
```

The worker builds the feed on a schedule and writes it to SQLite. The API reads feeds, records ratings, manages curation, and serves playback. Only the Gateway talks to YouTube.

### Core modules (`packages/core/src/homefeed_core/`)

| Module | Public interface (sketch) | Hides |
| --- | --- | --- |
| `gateway` | `get_video(id)`, `get_formats(id)`, `get_related(id)`, `search(query, filters)`, `get_channel_uploads(channel_id)`, `get_featured_channels(channel_id)`, `get_captions(id)`, `get_comments(id)`, `resolve_url(url)` → normalized domain dataclasses | yt-dlp options, PO tokens, retries with backoff, rate limiting, response caching, failure recording into `extractor_events` |
| `poller` | `poll_due_channels() -> list[VideoId]` | RSS fetching and parsing, per-channel schedule and backoff |
| `candidates` | `generate() -> list[Candidate]`; each source implements `CandidateSource.fetch()` | Deduplication, first-seen tracking, source attribution, isolating failing sources |
| `enricher` | `enrich(video_id) -> VideoFeatures` | Metadata, transcript excerpt (first ~5 min of captions), embedding, LLM tags, cache and version tracking |
| `ranker` | `rank(candidates, features, model, curation, n_ratings) -> list[ScoredCandidate]` | Hard filters, similarity features, model inference, channel shrinkage, topic boosts, blend, score breakdown |
| `composer` | `compose(scored, curation, settings, rng) -> Feed` | Pins, per-channel caps, exploration slots, selection probabilities, explanations |
| `trainer` | `train() -> ModelVersion`, `activate(version_id)` | Dataset building, label weighting, time decay, evaluation, promotion rule, model files |
| `curation` | CRUD for channel prefs, topics, keyword mutes, saved searches, external sources | Persistence, topic embeddings, boost decay |
| `playback` | `manifest(video_id) -> str`, `proxy_range(video_id, itag, range)`, `sponsor_segments(video_id)` | Stream resolution via Gateway, DASH MPD generation, URL expiry and refresh |
| `importer` | `import_takeout(file) -> ImportReport` | Takeout JSON/HTML parsing, seeding channels and candidates (never ratings) |
| `db` | Session factory, migrations | SQLite setup, WAL, sqlite-vec loading, schema migrations (use Alembic or a simple versioned migration runner) |

## 7. Ranking specification

**Labels.** Explicit rating value from section 3, weight 1.0. Implicit weak negatives: dismissed from feed = value −0.5 at weight 0.3; abandoned within 60 seconds = value −0.5 at weight 0.2. Rated videos ignore implicit signals.

**Time decay.** Training weight × `0.5 ** (age_days / 180)`.

**Hard filters (before scoring).** Shorts (duration < 60s or Shorts URL), live/upcoming, outside duration bounds, muted channels, muted keywords (title/description), already watched, already dismissed.

**Features.** Embedding (384-dim); max and mean cosine similarity to the top-tier set and to the bottom-tier set; duration (log); upload age (log days); candidate source (categorical); LLM tags when present (topic, depth, clickbait score, rage-bait score); channel score.

**Channel score (Bayesian shrinkage).**

```
channel_score = (sum(rating_values) + prior * k) / (n_ratings + k),   k = 5
priors: love = +0.8, like = +0.4, neutral = 0.0, skeptical = -0.4
```

**Topic boosts.** Each topic has a plain-language description (embedded) and a slider weight in [−1, 1]. `topic_boost = weight * max(0, cos_sim(video, topic) - 0.3) / 0.7`. Optional decay per topic: weight halves every 30 days unless reaffirmed. A topic can be backed by a tag (subscribing to it): with match mode `tag` it adds `weight * confidence` to videos carrying the tag, with `both` the larger in magnitude of the tag and embedding terms.

**Combination (log-odds-like space).**

```
alpha = n / (n + 50)             # n = number of explicit ratings
final = alpha * model_score + channel_boost + similarity + sum(topic_boosts)
similarity = 0.5 * (affinity(max_sim_top) - affinity(max_sim_bottom)),
             affinity(s) = max(0, s - 0.3) / 0.7
```

Before a model exists, `alpha = 0` and `model_score = 0`. Every scored item carries a breakdown `{model, alpha, channel, similarity, topics: {...}}` whose parts sum to `final`, plus the similarity features it came from (max, mean and nearest video for each tier set).

**Feed composition.** Default size 15. Order: pins first (new uploads from pinned channels), then exploration slots (default 3), then top-scored items, with at most 2 items per channel. Exploration uses Thompson sampling over per-channel `Beta(good + 1, not_good + 1)` posteriors (good = B-- or higher), restricted to channels with fewer than 5 ratings or never-rated sources. Estimate each item's selection probability by Monte Carlo (e.g. 500 draws) and store it.

**Explanations.** One line per item derived from its largest positive breakdown term and its source, e.g. "Related to *X* (A+) · channel you love" or "Exploring: new channel from your 'woodworking' search".

**Training and promotion.** Hold out the most recent 20% of explicit ratings by time. Metrics: Spearman correlation and MAE on the holdout. Promote a new model only if Spearman is not worse than the active model's by more than 0.02. Exclude pinned items from training; reweight exploration ratings by inverse selection probability (clipped). Keep the last 10 model versions for rollback.

## 8. Data model

Tables (SQLite): `channels`, `videos`, `video_features` (embedding in a sqlite-vec virtual table, plus tags and the model/prompt versions that produced them), `video_llm_tags` (topic, depth, clickbait, rage-bait per video and prompt version, with the model that produced them), `tags` (slug, label), `tag_aliases` (alias slug, tag, source auto|user), `video_tags` (video, tag, source llm|manual, confidence, prompt_version, removed_at tombstone), `candidates` (video, source, source_detail, first_seen), `tag_discovery_runs` (tag, last run), `feeds` (date, created_at, model_version), `feed_items` (feed, video, position, score breakdown JSON, explanation, is_exploration, selection_probability, dismissed_at, dismiss_reason), `ratings` (video, score, value, rated_at, updated_at), `watch_events` (video, position, event type, at), `channel_prefs` (prior, pinned, muted), `topics` (name, description, embedding, weight, decay, reaffirmed_at, tag_id, match_mode), `keyword_mutes`, `saved_searches` (query, filters, schedule), `external_sources` (kind, url, schedule), `queue_items`, `playlists`, `playlist_items`, `model_versions` (path, metrics JSON, created_at, active), `extractor_events` (operation, success, error, at), `settings`.

Store the score as a number (`7.4`) and the numeric value alongside it.

## 9. API contract (FastAPI, JSON)

| Area | Endpoints |
| --- | --- |
| Feed | `GET /feed/today`, `GET /feed/{date}`, `GET /feeds` (history), `POST /feed/refresh`, `POST /feed-items/{id}/dismiss` `{reason?}` |
| Videos | `GET /videos/{id}`, `GET /videos/{id}/manifest.mpd`, `GET /videos/{id}/media/{itag}` (Range proxy), `GET /videos/{id}/comments`, `GET /videos/{id}/segments` (SponsorBlock), `POST /resolve` `{url}` |
| Ratings and watching | `GET /ratings/{video_id}`, `PUT /ratings/{video_id}` `{score}`, `DELETE /ratings/{video_id}`, `POST /watch-events` `{video_id, event_type, position, duration}` |
| Library | `GET/POST/PATCH/DELETE /queue`, `GET /history?q=`, `/playlists` CRUD |
| Curation | `/channels` (subscribe by URL, list, update prior/pin/mute, unsubscribe), `/topics`, `/keyword-mutes`, `/saved-searches`, `/external-sources` |
| Discovery | `GET /search?q=&filters`, `GET /channels/{id}/uploads`, `GET /channels/{id}/featured`, `GET /discover/suggested-channels` |
| Insights and models | `GET /insights/weekly` (good rate, score distribution, rating rate, model vs curation share), `GET /models`, `POST /models/{id}/activate` |
| Ops | `GET /health`, `GET /status/extractors`, `POST /import/takeout`, `GET /export` |

Auth lives in the web app (single password, session cookie). The API binds to the internal Docker network only.

## 10. Frontend routes

`/` home feed · `/watch/$videoId` · `/queue` · `/history` · `/curation` (tabs: channels, topics, mutes, searches, sources) · `/discover` · `/insights` · `/settings` · `/status` · `/login`.

Home feed items show thumbnail, channel avatar, title, channel, duration, view count, upload age, explanation (expandable to the score breakdown), and status icons (pinned, exploring, dismissed). The watch page shows chapters, description, and comments on demand, skips SponsorBlock segments, saves resume position, and ends in the rating prompt. It never shows suggested videos and never autoplays.

## 11. Milestones

Each milestone ends with tests passing, lint clean, and a short summary of what changed and what's next.

### Milestone 1: watch, rate, and a rules-only feed

- `db` with migrations for the tables needed here.
- `gateway`: `get_video`, `get_formats`, `get_channel_uploads`, `resolve_url`, with recorded-fixture tests.
- `poller` with channel subscriptions via RSS.
- `curation`: channel prefs (prior, pin, mute).
- `ranker` (filters + channel score only) and `composer` (pins, caps; no exploration yet).
- Worker job: poll → candidates (subscriptions only) → rank → compose daily feed.
- `playback`: **spike first** on DASH. Determine how to get `initRange`/`indexRange` for adaptive formats (InnerTube player response, yt-dlp internals, or probing the `sidx` box with a small range request). Fallback: remux to fragmented MP4 with ffmpeg on the fly. Report findings before building the full player.
- Web: login, home feed, watch page with Shaka Player, rating prompt, channel subscribe/prior/pin/mute UI.

### Milestone 2: content understanding

- `enricher`: metadata, transcript excerpt, embeddings into sqlite-vec.
- `ranker`: similarity features (to top-tier and bottom-tier sets), topic boosts, keyword mutes, full breakdown.
- `curation`: topics with sliders and optional decay; keyword mutes.
- Candidate source: related videos of top-tier rated videos.
- Web: explanations and breakdown popover, topics and mutes UI, text-only mode toggle.

### Milestone 3: learning

- `trainer` with dataset building, weighting, decay, promotion, versioning, and rollback; nightly job.
- `ranker`: model inference and the alpha blend.
- `composer`: exploration slots with Thompson sampling and selection probabilities.
- Web: insights page (good rate trend, score distribution, rating rate, model vs curation share), model list with rollback, exploration badges, dismiss with reason.

### Milestone 4: broader discovery

- Candidate sources: saved searches, channel graph (featured channels of liked channels), external sources (subreddit JSON, RSS, link extraction), tag discovery (a daily YouTube search per subscribed tag, capped per tag per day).
- `importer`: Google Takeout watch history.
- LLM tagging behind the provider interface (topic, depth, clickbait, rage-bait, and 3–8 specific tags resolved to a canonical vocabulary through aliases), cached per video and prompt version. Default provider: hosted OpenRouter (see Decisions in section 13).
- Web: discover page, search with filters, suggested channels, saved searches and sources UI, Takeout upload.

### Milestone 5: library, ops, and deployment

- Queue, history search, local playlists, resume positions.
- SponsorBlock segments, comments, chapters.
- Status page from `extractor_events`; scheduled live smoke test of the Gateway (not in CI).
- Full JSON export.
- Dockerfiles (web via `turbo prune @homefeed/web --docker`; Python images via `uv sync --package <name> --frozen`) and `docker-compose.yml` with a shared data volume.
- Playwright flows: view feed, watch and rate, dismiss, edit a channel prior.

## 12. Testing

Test each module through its public interface; assert behavior, not internals.

| Module | What to test |
| --- | --- |
| `ranker` | Filters remove Shorts, muted channels/keywords, out-of-range durations; channel score moves from prior toward evidence as ratings grow; alpha is 0 with no ratings; breakdown sums to the final score |
| `composer` | Exact feed size; pins always included; per-channel cap; exploration slot count; probabilities recorded; deterministic with a seeded rng |
| `trainer` | Score → value mapping across the 1 to 10 range; implicit weights; time decay; pinned items excluded; worse model not promoted; rollback works (use synthetic histories with a learnable pattern) |
| `candidates` | Dedup across sources; source attribution; one failing source doesn't fail the run (fake sources) |
| `enricher` | Cache hits skip work; version change recomputes; missing captions handled (stub embedding/LLM providers) |
| `gateway` | Normalization from recorded responses; failure recording. Live smoke suite is opt-in only |
| `importer` | Takeout parsing incl. malformed and removed-video entries |
| API | Contract tests per endpoint against a temp SQLite DB with a fake Gateway |

## 13. Risks and notes

- **YouTube breakage** (signature/throttling changes, PO tokens, protocol changes) is the main operational risk. Keep yt-dlp updated, isolate everything in the Gateway, make the feed usable from cached data when extraction fails, and add a PO-token provider plugin only if needed.
- **Terms of Service:** undocumented endpoints go against YouTube's terms; personal-use risk is mostly IP throttling. No Google account is used.
- **Rate limits:** stay at personal-use volume, roughly a few hundred enrichments per day, with caching.
- **Small data:** hundreds of labels, not millions. Keep models simple and lean on curation priors until about 200 ratings.
- **Rating fatigue:** rating must take one drag and one tap, and the prompt is skippable. Track the rating rate.

### Decisions

- **LLM provider default: hosted API via OpenRouter**, decided before Milestone 4. `LLM_PROVIDER=openrouter|ollama|none`, with `OPENROUTER_API_KEY`, `LLM_MODEL` (default `google/gemini-2.5-flash-lite`: cheap, fast, non-reasoning, multilingual, supports JSON mode), `LLM_BASE_URL` (default `https://openrouter.ai/api/v1`). Requests use the OpenAI-compatible `POST /chat/completions` with a bearer key, `response_format: json_object` and the optional `X-Title` attribution header. Without a key, tagging is logged and skipped; it never fails a job. Ollama remains supported for local use.

### Open questions

- Should topic boosts decay by default?
- Feed size and refresh time after real use (defaults: 15 items at 06:00).
