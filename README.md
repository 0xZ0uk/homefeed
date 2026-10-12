# Homefeed

A self-hosted, single-user YouTube client with a finite daily home feed ranked by a model trained on tier-list ratings. See [PLAN.md](PLAN.md) for the full design and milestones.

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

## Database

API and worker share one SQLite file (`DATABASE_PATH`), opened through `homefeed_core.db.get_session_factory()`, which applies pending migrations on startup. To change the schema, add the next numbered file to `packages/core/src/homefeed_core/db/migrations/` (e.g. `0002_ratings.sql`); never edit an applied one.

## Layout

- `apps/api`: FastAPI app (`homefeed_api`), http://localhost:8000 in dev
- `apps/worker`: APScheduler worker (`homefeed_worker`)
- `apps/web`: TanStack Start frontend (`@homefeed/web`), served on http://localhost:3000 in dev
- `packages/api-client`: TypeScript client generated from the API's OpenAPI schema (`@homefeed/api-client`)
- `packages/core`: Python domain logic (`homefeed_core`)
- `packages/typescript-config`: shared `tsconfig.json` bases
- `packages/eslint-config`: shared ESLint configurations
