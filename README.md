# Homefeed

A self-hosted, single-user YouTube client with a finite daily home feed ranked by a model trained on 1 to 10 ratings. See [PLAN.md](PLAN.md) for the full design and milestones.

## Development

The JS package manager is nub; Python packages are managed with [uv](https://docs.astral.sh/uv/). Turborepo orchestrates both.

Copy `.env.example` to `.env` and adjust.

```sh
nub install
uv sync --all-packages
nub run dev    # start all apps (except the desktop shell, see below)
nub run test   # run tests across packages
nub run lint   # lint across packages
```

## Enrichment and tagging by hand

The worker enriches and tags new videos every 30 minutes. To run it now, with a progress bar:

```sh
nub run reembed        # re-embed videos and tags made by another EMBEDDING_MODEL
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
cp .env.example .env   # set APP_PASSWORD, SESSION_SECRET, TZ, ...
docker compose up -d --build
```

Open `http://<host>:3000` (set `WEB_PORT` in `.env` to change the port). Only `web` publishes a port; `api` is reachable only from the other containers on the compose network (`API_URL` is set to `http://api:8000` for you). `api` and `worker` share the `homefeed_data` volume at `/data`, which holds the SQLite database, trained models and the embedding model cache; `DATA_DIR`/`DATABASE_PATH` from `.env` are overridden to point there.

All three images come from the root `Dockerfile` (targets `api`, `worker`, `web`):

- `api`/`worker`: `uv sync --package homefeed-api|homefeed-worker --frozen --no-dev` into a self-contained venv.
- `web`: `turbo prune @homefeed/web --docker`, then `nub ci` and `turbo run build`. turbo writes the pruned `nub.lock` as `pnpm-lock.yaml` (same format), so the Dockerfile renames it back. The API client is generated from an OpenAPI schema exported in the `openapi` stage, so the web build needs no Python. The image serves the build with [srvx](https://srvx.h3.dev).

## Desktop mode

The Electron shell runs the web server with `HOMEFEED_MODE=desktop` (unset or `server` is the password login above). There is no login page: the server returns a plain 401 ("Open Homefeed from the desktop app") to anything without a session, `/login` and `/logout` are 404, and the log out button is hidden. The shell starts a session by opening `GET /desktop-auth?token=<DESKTOP_TOKEN>&next=<path>`; a matching token sets the session cookie and redirects to `next` (a same-origin path, default `/`), anything else gets 403. The cookie is `HttpOnly`, `SameSite=Lax` and not `Secure` (the app is served over `http://127.0.0.1`).

Env the shell must set for the web process (started as `srvx serve --prod --entry=dist/server/server.js --static=../client`, which reads `HOST` and `PORT`):

- `HOMEFEED_MODE=desktop`
- `HOST=127.0.0.1`: srvx otherwise listens on all interfaces, so other machines on the network could reach it.
- `PORT`: any free port.
- `API_URL`: where the API listens, e.g. `http://127.0.0.1:8000`.
- `DESKTOP_TOKEN`: per-launch secret, at least 32 characters (`APP_PASSWORD` is not used).
- `SESSION_SECRET`: per-launch, at least 32 characters.

Start the API bound to `127.0.0.1` too (`uvicorn homefeed_api.main:app --host 127.0.0.1 --port <port>`); it has no auth of its own.

## Desktop app (development)

`apps/desktop` (`@homefeed/desktop`) is the Electron shell that does all of the above: it starts the API (with `RUN_WORKER_IN_API=true`) and the web server on free `127.0.0.1` ports with per-launch secrets, opens the app in a window, and keeps running in the tray. To run it from the repo (after `nub install` and `uv sync --all-packages`):

```sh
nub run desktop                                            # builds apps/web, then runs `electron .`
HOMEFEED_USER_DATA_DIR=/tmp/homefeed-test nub run desktop  # with a throwaway profile
```

It keeps its data, logs and window state in Electron's user data dir (`~/.config/Homefeed` on Linux), never the repo's `data/` or `.env`. See [apps/desktop/README.md](apps/desktop/README.md) for what it runs, where it logs, and the runtime layout a packaged build must have.

Installers (Windows NSIS, Linux AppImage) are built by `.github/workflows/desktop-release.yml` on `desktop-v*` tags and published to a public releases repo the app updates from; see "Building installers" and "Releasing" in [apps/desktop/README.md](apps/desktop/README.md). [apps/desktop/INSTALL.md](apps/desktop/INSTALL.md) is the install guide for people you share it with.

## Layout

- `apps/api`: FastAPI app (`homefeed_api`), http://localhost:8000 in dev
- `apps/worker`: APScheduler worker (`homefeed_worker`)
- `apps/web`: TanStack Start frontend (`@homefeed/web`), served on http://localhost:3000 in dev
- `apps/desktop`: Electron shell (`@homefeed/desktop`) running the API and web app as a desktop app
- `packages/api-client`: TypeScript client generated from the API's OpenAPI schema (`@homefeed/api-client`)
- `packages/core`: Python domain logic (`homefeed_core`)
- `packages/typescript-config`: shared `tsconfig.json` bases
- `packages/eslint-config`: shared ESLint configurations

## Settings

The feed size and discovery slots, video length bounds, the daily feed and training times, the time zone, LLM tagging (provider, model, OpenRouter API key, videos per run), tag discovery per day and the SponsorBlock categories to skip are edited on the Settings page (API: `GET`/`PATCH /settings`) and stored in the database's `settings` table (`homefeed_core.user_settings`). Until changed there, each follows its `.env` variable (marked `[Settings]` in `.env.example`) or built-in default, so an install configured through `.env` keeps working; "Reset to default" goes back to it. The time zone defaults to the system's (`TZ`) and decides what "today" is and when the daily jobs run. Schedule changes reach the worker (or the API's in-process scheduler) within a minute, without a restart. The OpenRouter API key is kept in plain text in the local SQLite file, like the rest of your data, and the API only ever returns its last four characters. Everything else (paths, URLs, timeouts, embeddings, calibration) stays in `.env`.

## Running the worker inside the API

By default the scheduled jobs (polling, enrichment, the daily feed, nightly training) run in the separate `worker` process, which is what Docker Compose does. Set `RUN_WORKER_IN_API=true` to run them on a background thread of the API process instead (one process, e.g. for a desktop app), and don't start a worker then. Either way, a process that starts after the daily feed or training time (see Settings; a laptop that was asleep or off) builds today's feed and trains the model right away if they're missing or overdue.

## Extractor status and live smoke test

`/status` (API: `GET /status/extractors`) shows how requests to YouTube have been going, aggregated from `extractor_events`. The live Gateway smoke test runs one request per Gateway operation against real YouTube and records the outcome there too. It uses the network, so it is opt-in and never part of `nub run test` or CI: set `GATEWAY_SMOKE_TEST_TIME` (e.g. `05:30`) for the worker to run it daily, or run it by hand with `uv run python -m homefeed_core.smoke_test`. The pytest equivalents run only with `HOMEFEED_LIVE_TESTS=1`.
