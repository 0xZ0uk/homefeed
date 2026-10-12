# Homefeed

A self-hosted, single-user YouTube client with a finite daily home feed ranked by a model trained on tier-list ratings. See [PLAN.md](PLAN.md) for the full design and milestones.

## Development

The JS package manager is nub; Python packages are managed with [uv](https://docs.astral.sh/uv/). Turborepo orchestrates both.

```sh
nub install
nub run dev    # start all apps
nub run test   # run tests across packages
nub run lint   # lint across packages
```

## Layout

- `packages/typescript-config`: shared `tsconfig.json` bases
- `packages/eslint-config`: shared ESLint configurations
