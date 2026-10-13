# Homefeed

A self-hosted, single-user YouTube client with a finite daily home feed ranked by a model trained on 1 to 10 ratings. See [PLAN.md](PLAN.md) for the full design and milestones.

## Development

The JS package manager is nub; Python packages are managed with [uv](https://docs.astral.sh/uv/). Turborepo orchestrates both.

Copy `.env.example` to `.env` and adjust.

```sh
nub install
uv sync --all-packages
nub run dev    # start all apps
nub run test   # run tests across packages
nub run lint   # lint across packages
```

## Enrichment and tagging by hand

The worker enriches and tags new videos every 30 minutes. To run it now, with a progress bar:

```sh
nub run reembed        # re-embed videos, topics and tags made by another EMBEDDING_MODEL
nub run enrich         # what the worker does: re-embed, enrich the next feed's candidates, tag them
nub run tag            # tag only (same videos as the worker); add --all for every stored video, --limit N to cap LLM calls
```

## End-to-end tests

Playwright flows in `apps/e2e` (view the feed, watch and rate, dismiss, edit a channel prior) run the real web app (`vite dev`) and API against a fake Gateway with a throwaway data dir, so they never touch YouTube or your `data/`. The API side is `apps/e2e/fake_api.py`, which seeds two channels and today's feed; tests reset it before each run.

```sh
nub run --filter @homefeed/e2e e2e:install   # once: download Chromium for Playwright
nub run e2e                                  # turbo run e2e
```

They use ports 8799 (API) and 3799 (web); override with `E2E_API_PORT` / `E2E_WEB_PORT`. `e2e` isn't part of `nub run test`.

## Database

API and worker share one SQLite file (`DATABASE_PATH`), opened through `homefeed_core.db.get_session_factory()`, which applies pending migrations on startup. To change the schema, add the next numbered file to `packages/core/src/homefeed_core/db/migrations/` (e.g. `0002_ratings.sql`); never edit an applied one.

## Deployment (Docker Compose)

```sh
cp .env.example .env   # set APP_PASSWORD, SESSION_SECRET, TZ, OPENROUTER_API_KEY, ...
docker compose up -d --build
```

Open `http://<host>:3000` (set `WEB_PORT` in `.env` to change the port). Only `web` publishes a port; `api` is reachable only from the other containers on the compose network (`API_URL` is set to `http://api:8000` for you). `api` and `worker` share the `homefeed_data` volume at `/data`, which holds the SQLite database, trained models and the embedding model cache; `DATA_DIR`/`DATABASE_PATH` from `.env` are overridden to point there.

All three images come from the root `Dockerfile` (targets `api`, `worker`, `web`):

- `api`/`worker`: `uv sync --package homefeed-api|homefeed-worker --frozen --no-dev` into a self-contained venv.
- `web`: `turbo prune @homefeed/web --docker`, then `nub ci` and `turbo run build`. turbo writes the pruned `nub.lock` as `pnpm-lock.yaml` (same format), so the Dockerfile renames it back. The API client is generated from an OpenAPI schema exported in the `openapi` stage, so the web build needs no Python. The image serves the build with [srvx](https://srvx.h3.dev).

## Layout

- `apps/api`: FastAPI app (`homefeed_api`), http://localhost:8000 in dev
- `apps/worker`: APScheduler worker (`homefeed_worker`)
- `apps/web`: TanStack Start frontend (`@homefeed/web`), served on http://localhost:3000 in dev
- `packages/api-client`: TypeScript client generated from the API's OpenAPI schema (`@homefeed/api-client`)
- `packages/core`: Python domain logic (`homefeed_core`)
- `packages/typescript-config`: shared `tsconfig.json` bases
- `packages/eslint-config`: shared ESLint configurations

## Extractor status and live smoke test

`/status` (API: `GET /status/extractors`) shows how requests to YouTube have been going, aggregated from `extractor_events`. The live Gateway smoke test runs one request per Gateway operation against real YouTube and records the outcome there too. It uses the network, so it is opt-in and never part of `nub run test` or CI: set `GATEWAY_SMOKE_TEST_TIME` (e.g. `05:30`) for the worker to run it daily, or run it by hand with `uv run python -m homefeed_core.smoke_test`. The pytest equivalents run only with `HOMEFEED_LIVE_TESTS=1`.
