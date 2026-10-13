# syntax=docker/dockerfile:1
#
# One Dockerfile, one target per service (see docker-compose.yml):
#
#   docker build --target api    -t homefeed-api .
#   docker build --target worker -t homefeed-worker .
#   docker build --target web    -t homefeed-web .
#
# The web build needs the API's OpenAPI schema to generate `@homefeed/api-client`;
# the `openapi` stage exports it from the API image's environment, so the web image
# never needs Python or uv.

ARG PYTHON_VERSION=3.13
ARG NODE_VERSION=24
ARG UV_VERSION=0.12.24

# ---------------------------------------------------------------------------
# Python (api + worker): `uv sync --package <name> --frozen`
# ---------------------------------------------------------------------------

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim AS python-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# libgomp1: LightGBM's OpenMP runtime. tzdata: so TZ (feed refresh / training times) works.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 tzdata \
    && rm -rf /var/lib/apt/lists/*

FROM python-base AS python-build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
# Every workspace member's pyproject.toml is needed to read the workspace, even
# when syncing a single package.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY apps/worker/pyproject.toml apps/worker/
COPY packages/core/pyproject.toml packages/core/

FROM python-build AS api-build
# Third-party dependencies first (cached until uv.lock changes), then the workspace
# packages themselves, installed non-editable so the venv is self-contained.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package homefeed-api --frozen --no-dev --no-editable --no-install-workspace
COPY packages/core/src packages/core/src
COPY apps/worker/src apps/worker/src
COPY apps/api/src apps/api/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package homefeed-api --frozen --no-dev --no-editable

FROM python-build AS worker-build
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package homefeed-worker --frozen --no-dev --no-editable --no-install-workspace
COPY packages/core/src packages/core/src
COPY apps/worker/src apps/worker/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package homefeed-worker --frozen --no-dev --no-editable

FROM python-base AS python-runtime
# One unprivileged user for api and worker, owning /data so a fresh named volume
# mounted there inherits that ownership.
RUN useradd --create-home --uid 1000 homefeed \
    && mkdir /data \
    && chown homefeed:homefeed /data
ENV PATH=/app/.venv/bin:$PATH \
    DATA_DIR=/data \
    DATABASE_PATH=/data/homefeed.sqlite
WORKDIR /app
USER homefeed

FROM python-runtime AS api
COPY --from=api-build /app/.venv /app/.venv
EXPOSE 8000
# A single process: the Gateway's rate limiting and playback caches are per process.
CMD ["uvicorn", "homefeed_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python-runtime AS worker
COPY --from=worker-build /app/.venv /app/.venv
CMD ["python", "-m", "homefeed_worker"]

# Same output as `nub run openapi` in apps/api (homefeed_api.export_openapi writes
# next to its own source, which is inside site-packages in a non-editable install).
FROM api-build AS openapi
RUN DATA_DIR=/tmp/data DATABASE_PATH=/tmp/data/homefeed.sqlite /app/.venv/bin/python -c \
    'import json; from homefeed_api.main import app; print(json.dumps(app.openapi(), indent=2))' \
    > /openapi.json

# ---------------------------------------------------------------------------
# Web: `turbo prune @homefeed/web --docker`, installed with nub
# ---------------------------------------------------------------------------

FROM node:${NODE_VERSION}-slim AS node-base
# Keep in sync with package.json (devEngines.packageManager and the turbo devDependency).
ARG NUB_VERSION=0.9.6
ARG TURBO_VERSION=2.11.7
ENV TURBO_TELEMETRY_DISABLED=1
# Installed from / : npm refuses to run inside the repo because of devEngines (nub).
RUN npm install --global "@nubjs/nub@${NUB_VERSION}" "turbo@${TURBO_VERSION}" \
    && npm cache clean --force
WORKDIR /app

FROM node-base AS web-prune
COPY . .
# turbo reads nub.lock (pnpm v9 format) but writes the pruned lockfile as
# pnpm-lock.yaml; rename it so the pruned workspace looks like the real one.
RUN turbo prune @homefeed/web --docker \
    && if [ -f out/json/pnpm-lock.yaml ]; then mv out/json/pnpm-lock.yaml out/json/nub.lock; fi \
    && test -f out/json/nub.lock

FROM node-base AS web-build
COPY --from=web-prune /app/out/json/ .
RUN nub ci
COPY --from=web-prune /app/out/full/ .
COPY --from=openapi /openapi.json apps/api/openapi.json
# `--only`: skip `@homefeed/api#openapi` (needs uv); its output was copied in above.
RUN turbo run generate --filter=@homefeed/api-client --only \
    && turbo run build --filter=@homefeed/web --only

FROM node-base AS web-deps
COPY --from=web-prune /app/out/json/ .
RUN nub ci --prod --filter @homefeed/web

FROM node:${NODE_VERSION}-slim AS web
# The build emits a fetch handler (dist/server/server.js) plus static assets
# (dist/client); srvx serves both on Node. Keep in sync with the srvx version in
# nub.lock (a dependency of @tanstack/react-start).
ARG SRVX_VERSION=0.11.22
RUN npm install --global "srvx@${SRVX_VERSION}" && npm cache clean --force
ENV NODE_ENV=production \
    PORT=3000
WORKDIR /app
COPY --from=web-deps /app/node_modules ./node_modules
COPY --from=web-deps /app/apps/web/node_modules ./apps/web/node_modules
COPY --from=web-build /app/apps/web/package.json ./apps/web/package.json
COPY --from=web-build /app/apps/web/dist ./apps/web/dist
WORKDIR /app/apps/web
USER node
EXPOSE 3000
# --static is resolved relative to the entry's directory.
CMD ["srvx", "serve", "--prod", "--entry=dist/server/server.js", "--static=../client"]
