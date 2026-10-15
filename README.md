# Homefeed

A YouTube client with a finite daily home feed, ranked by a model trained on your own 1 to 10 ratings.

<!-- TODO: screenshot of the feed, e.g. ![Homefeed's daily feed](docs/screenshot.png) -->

Homefeed is built against compulsion. Once a day it builds a fixed number of videos from the channels you follow plus a few it thinks you'll like, and that's the feed: no infinite scroll, no autoplay, no "up next". Every video says why it's there. Rate what you watch from 1 to 10 and a model trained nightly on those ratings ranks tomorrow's feed. The number it optimizes is how many of the videos you rate score 6 or higher, not how long you watch.

It runs on your own computer or server and keeps everything there. There's no account to sign in with, YouTube or otherwise.

## Features

- **A finite daily feed**: a set number of videos (20 by default), rebuilt once a day at a time you choose.
- **Learns from ratings**: rate videos 1 to 10; the ranking model retrains every night on them.
- **Explains itself**: every video says why it's in the feed, and you can steer it by dismissing videos, changing how much you like a channel, or following topics.
- **Discovery that doesn't trap you**: a few slots each day go to channels you haven't rated much, and no single topic can take over the feed.
- **Optional LLM tagging**: tags videos by topic, depth, clickbait and rage-bait (through [OpenRouter](https://openrouter.ai) or a local [Ollama](https://ollama.com)) to rank them better.
- **SponsorBlock**: skips sponsor segments and other categories you choose.
- **Private**: your feed, ratings and model stay in a local SQLite file. Homefeed doesn't use the YouTube Data API or a Google account.

## Install

### Desktop app (Windows, Linux)

Download the latest installer from [Releases](../../releases/latest):

- **Windows**: `Homefeed-Setup-<version>.exe`
- **Linux**: `Homefeed-<version>-x86_64.AppImage`

The app updates itself. Installers aren't code-signed, so Windows SmartScreen warns the first time; see the [install guide](apps/desktop/INSTALL.md) for that and everything else (where your data lives, uninstalling).

### Self-hosted (Docker Compose)

For a server on your home network, behind a password:

```sh
git clone https://github.com/0xZ0uk/homefeed.git
cd homefeed
cp .env.example .env   # set APP_PASSWORD, SESSION_SECRET, TZ, ...
docker compose up -d --build
```

Open `http://<host>:3000` (set `WEB_PORT` in `.env` to change the port). Only `web` publishes a port; `api` is reachable only from the other containers on the compose network (`API_URL` is set to `http://api:8000` for you). `api` and `worker` share the `homefeed_data` volume at `/data`, which holds the SQLite database, trained models and the embedding model cache; `DATA_DIR`/`DATABASE_PATH` from `.env` are overridden to point there.

Homefeed is single-user and meant for a home network or VPN, not the open internet.

## Configuration

Most settings (feed size, discovery slots, video length bounds, the daily feed and training times, time zone, LLM tagging, SponsorBlock categories) are on the app's Settings page. The rest (paths, embeddings, timeouts) are in `.env`; [`.env.example`](.env.example) documents every variable.

## Development

Homefeed is a Turborepo monorepo: a FastAPI backend and scheduler in Python (managed with [uv](https://docs.astral.sh/uv/)), a [TanStack Start](https://tanstack.com/start) web app, and an Electron shell for the desktop app.

```sh
cp .env.example .env
nub install
uv sync --all-packages
nub run dev    # start the API, worker and web app
nub run test
```

[docs/development.md](docs/development.md) covers the rest: the repo layout, the database, end-to-end tests, desktop mode and running jobs by hand. Desktop releases are built and published by CI when a `desktop-v*` tag is pushed; see [Releasing](apps/desktop/README.md#releasing).

## Disclaimer

Homefeed isn't affiliated with or endorsed by YouTube or Google. It fetches public data with [yt-dlp](https://github.com/yt-dlp/yt-dlp), which may break when YouTube changes; the app's Status page shows how requests to YouTube have been going. Use it in line with the terms that apply to you.

## License

TODO: choose a license (e.g. MIT, AGPL-3.0) and add a `LICENSE` file.
