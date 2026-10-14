# @homefeed/desktop

The Electron shell: Homefeed as a desktop app. It starts the Python API (with the worker's jobs in the same process, `RUN_WORKER_IN_API=true`) and the web server (`HOMEFEED_MODE=desktop`) as child processes, then shows the web app in a window. Closing the window hides it to the tray so feeds keep refreshing; Quit (tray menu) stops everything.

Main process only, compiled with plain `tsc` (`src/main/` → `dist/main/`, ES modules). There is no renderer code: the window loads the web app over HTTP, the splash is a `data:` URL and the error window is a native message box, so no bundler or preload script is needed.

## Running it (development)

From the repo root, after `nub install` and `uv sync --all-packages`:

```sh
nub run desktop
```

That builds `@homefeed/web` and this package (`turbo run build --filter=@homefeed/desktop...`), then runs `electron .` here. `nub run --filter @homefeed/desktop dev` skips the web build (rebuild it yourself after changing `apps/web`). Electron downloads its binary on the first run.

It uses your real desktop profile (`~/.config/Homefeed` on Linux), not the repo's `data/` or `.env`. To try it against a throwaway profile:

```sh
HOMEFEED_USER_DATA_DIR=/tmp/homefeed-desktop-test nub run desktop
```

If Electron starts as plain Node (`does not provide an export named 'BrowserWindow'`), `ELECTRON_RUN_AS_NODE` is set in your shell; unset it.

The desktop shell isn't part of `nub run dev`. `nub run test|lint|check-types` cover it; unit tests never launch Electron.

## What it does on launch

1. Takes the single-instance lock (a second launch shows the existing window and exits).
2. Picks two free ports on `127.0.0.1` (API, web) and generates `DESKTOP_TOKEN` and `SESSION_SECRET` (32 random bytes each, new every launch).
3. Starts the API and the web server (see below), showing a splash window until the API answers `GET /health` with 200 and the web server answers at all (401 without a session). Startup times out after 120 s.
4. Opens the main window at `http://127.0.0.1:<web>/desktop-auth?token=…&next=/`, which signs in and redirects to the feed.

With `--hidden` (how "Start at login" launches it) there is no splash or window; the app starts in the tray.

On failure (missing files, a child exiting while starting, timeout) both children are stopped and an error box offers Retry, Open logs and Quit. A child that dies later is restarted, at most 3 times per 10 minutes; then the error box.

The window is sandboxed (`contextIsolation`, no `nodeIntegration`, `sandbox`), may only navigate within the web server's origin, and opens other `http(s):`/`mailto:` links in the default browser; new windows are denied (same-origin ones load in the main window). Only the `fullscreen` and `clipboard-sanitized-write` permissions are granted. Its size, position and maximized state are saved in `window-state.json`.

Tray menu: Open Homefeed, Start at login (packaged builds only: Windows uses `app.setLoginItemSettings`, Linux an XDG autostart entry `~/.config/autostart/homefeed.desktop` pointing at the AppImage), Open data folder, Open logs, Quit Homefeed; plus "Restart to update" once an update is downloaded (see [Updates](#updates)).

## Files

Under Electron's `userData` (`~/.config/Homefeed` on Linux, `%APPDATA%\Homefeed` on Windows), or `HOMEFEED_USER_DATA_DIR`:

- `data/`: `DATA_DIR` (database `homefeed.sqlite` = `DATABASE_PATH`, models, embedding model cache).
- `logs/`: `main.log` (the shell), `api.log`, `web.log` (children's stdout/stderr; the token is masked). Each rotates at 5 MB to `name.1.log`, `name.2.log`.
- `window-state.json`.

## Child processes

Both children inherit the shell's environment plus the variables below. On Linux/macOS they are spawned detached (own process group) and stopped with SIGTERM to the group, then SIGKILL after 5 s; on Windows with `taskkill /pid <pid> /T /F`. If the shell exits any other way, a `process.on("exit")` handler kills both trees. (A shell killed with SIGKILL can't clean up: its children are orphaned.)

**API** (cwd: the data dir):

```
<python> -I -u -X utf8 -m uvicorn homefeed_api.main:app --host 127.0.0.1 --port <api> --no-access-log
```

Env: `DATA_DIR`, `DATABASE_PATH`, `RUN_WORKER_IN_API=true`, `EMBEDDING_PROVIDER=local`, `EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`, `LLM_PROVIDER=openrouter` (tagging is skipped until a key is entered in Settings), `YTDLP_AUTO_UPDATE=true`, `HOMEFEED_JS_RUNTIME=<Electron executable>` and `ELECTRON_RUN_AS_NODE=1` (yt-dlp runs Electron as its Node; it passes Node's `--permission` flag, which Electron's Node accepts), `HOMEFEED_NO_DOTENV=1` (settings never read a `.env` file, e.g. a stray `~/.env` above the data dir). `PYTHONHOME`, `PYTHONPATH` and `VIRTUAL_ENV` are dropped; `-I` also ignores other `PYTHON*` variables and user site-packages.

**Web** (cwd: the web root):

```
<Electron executable> <srvx bin> serve --prod --entry=dist/server/server.js --static=../client
```

Env: `ELECTRON_RUN_AS_NODE=1`, `NODE_ENV=production`, `NO_COLOR=1`, `HOST=127.0.0.1`, `PORT=<web>`, `API_URL=http://127.0.0.1:<api>`, `HOMEFEED_MODE=desktop`, `DESKTOP_TOKEN`, `SESSION_SECRET`.

## Runtime layout

`src/main/paths.ts` is the contract; packaging must produce the packaged layout exactly.

### Dev (`electron .` in `apps/desktop`, `app.isPackaged` false)

|          | Path                                                                                                                             |
| -------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Python   | `<repo>/.venv/bin/python` (`.venv\Scripts\python.exe` on Windows), from `uv sync --all-packages`                                 |
| Web root | `<repo>/apps/web` after `vite build` (`dist/server/server.js`, `dist/client/`), dependencies from the workspace's `node_modules` |
| srvx     | this package's `srvx` devDependency (`srvx/bin/srvx.mjs`)                                                                        |

`<repo>` is two directories above `app.getAppPath()`. Dev runs the production web build rather than `vite dev`: it is the same code path as the packaged app, and `vite dev` would load the repo's `.env` into the web process.

### Packaged (`app.isPackaged`)

Under `process.resourcesPath` (`resources/` next to the executable on Windows and inside the AppImage):

```
resources/
  app.asar                      this package: package.json, dist/bundle/main.js, assets/icon.png
  python/                       standalone CPython (e.g. python-build-standalone, 3.13) with
                                homefeed-api and its dependencies installed into its own
                                site-packages, non-editable (as `uv sync --package homefeed-api
                                --frozen --no-dev --no-editable` would; uvicorn comes with
                                fastapi[standard])
    python.exe                  Windows interpreter
    bin/python3                 Linux interpreter
  web/                          apps/web after `vite build`, plus its production dependencies
    package.json                apps/web/package.json (its "type": "module" is required)
    dist/server/server.js       + dist/server/assets/**
    dist/client/**              static assets
    node_modules/               production dependencies of @homefeed/web, resolvable from
                                dist/server/ by Node's normal lookup (hoisted/flat, no
                                symlinks out of web/), including srvx at
                                node_modules/srvx/bin/srvx.mjs (pin the version in nub.lock)
```

The shell checks for the interpreter, `web/dist/server/server.js` and `web/node_modules/srvx/bin/srvx.mjs` before starting and reports what's missing. `app.asar` needs only this package's `package.json`, the bundled main process and `assets/icon.png`: `nub run build` also bundles `dist/main/` and its one runtime dependency, electron-updater, into `dist/bundle/main.js` (esbuild, `scripts/bundle-main.mjs`), so the asar has no `node_modules` (electron-builder can't read nub's store layout anyway). Dev runs the unbundled `dist/main/`. On Windows the shell sets the AppUserModelID `app.homefeed.desktop`; use the same `appId` for the installer.

## Icon

`assets/icon.svg` is a placeholder (TODO: a real icon); `assets/icon.png` (256×256) is rendered from it (`rsvg-convert -w 256 -h 256 icon.svg -o icon.png`) and used for the windows, the tray and the AppImage. `assets/icon.ico` (Windows: the executable, the installer and the shortcuts) is committed: 16, 24, 32 and 48 px as bitmaps plus the 256 px PNG, about 20 KB. Regenerate it when the icon changes: render each size with `rsvg-convert -w <n> -h <n> icon.svg`, then `magick 16.png 24.png 32.png 48.png 256.png icon.ico` (ImageMagick stores the 256 px image as a 256 KB bitmap; swapping in the PNG keeps the file small).

## Updates

Packaged builds update themselves with [electron-updater](https://www.electron.build/auto-update) (`src/main/updater.ts`): on Windows the NSIS install, on Linux only the AppImage (`APPIMAGE` set; electron-updater replaces that file). Dev builds and unpacked Linux builds don't check (`main.log` says why).

- 30 s after the app is first up, then every 6 hours, it checks the latest release of this repo (see [Releasing](#releasing)) and downloads a newer version in the background.
- When the download is done: a notification ("Update ready — restart Homefeed to install") and a "Restart to update (x.y.z)" item at the top of the tray menu. That item stops the API and web server first (the same shutdown as Quit: their files are about to be replaced), then runs the installer silently and starts the new version.
- Otherwise the update installs when Homefeed quits (`autoInstallOnAppQuit`), again after the children have stopped.
- Everything is logged to `main.log` (`updater info: …`). No release or no network is a logged error, nothing more.

Builds are unsigned, so the updater doesn't check a publisher signature (`verifyUpdateCodeSignature: false`); it checks the download's sha512 from the release's `latest.yml` / `latest-linux.yml`, fetched over HTTPS.

## Building installers

Installers are built natively: the Windows installer on Windows, the AppImage on Linux (the Python bundle is platform-specific). CI does both (`.github/workflows/desktop-release.yml`); by hand, from the repo root after `nub install` and `uv sync --all-packages`:

```sh
nub exec turbo run build --filter=@homefeed/desktop...   # web app + shell (dist/bundle/main.js)
nub run --filter @homefeed/desktop bundle:python         # build/python
nub run --filter @homefeed/desktop bundle:web            # build/web
nub run --filter @homefeed/desktop dist                  # build/release/: the installer for this OS
```

Outputs (all under the gitignored `build/`): `build/python`, `build/web` and `build/release/` (`Homefeed-Setup-<version>.exe` or `Homefeed-<version>-x86_64.AppImage`, its `.blockmap`, `latest*.yml` for the updater, and the unpacked app, e.g. `build/release/linux-unpacked/`).

- **`scripts/bundle-python.mjs`** (needs uv): installs CPython 3.13 (python-build-standalone's `install_only_stripped` build, through `uv python install --install-dir`, which verifies its sha256; the version is pinned in the script, the build by the uv version, which CI pins), copies it to `build/python`, installs `uv export --frozen --no-dev --package homefeed-api` with `--require-hashes` into its own site-packages, then homefeed-core, -worker and -api as wheels (non-editable). It drops test suites, Tk/IDLE, headers, `.pyi` stubs, console scripts and pip, compiles all bytecode with `--invalidation-mode unchecked-hash` (the AppImage is read-only, so nothing could be cached at runtime, and installers don't keep mtimes), and finally imports `homefeed_api.main`, lightgbm, sqlite-vec (loading the extension), onnxruntime, fastembed, yt-dlp and yt-dlp-ejs from the bundle with `-I`. About 500 MB on Linux (onnxruntime, scipy and numpy with their BLAS libraries are most of it).
- **`scripts/bundle-web.mjs`**: copies `apps/web`'s `package.json` and `dist/`, then builds a flat `node_modules` with only what the server build still imports (it bundles everything else; the script scans `dist/server` for bare imports: react, the TanStack routers, Base UI, lucide-react, shaka-player, …), their production dependencies, and srvx (this package's pinned devDependency). Packages are copied out of nub's store as real directories, hoisted where versions agree and nested where they don't; no symlinks. About 24 MB.
- **`electron-builder.config.mjs`**: appId `app.homefeed.desktop`, product name Homefeed, the asar holds only the shell, `build/python` and `build/web` become `resources/python` and `resources/web`. Windows: a one-click, per-user NSIS installer (no admin prompt and no questions: the friendliest option for people who just want it installed; it goes to `%LOCALAPPDATA%\Programs\Homefeed`, adds Start Menu and desktop shortcuts, and starts the app), x64. Linux: an x64 AppImage. Unsigned (`forceCodeSigning: false`; CI sets `CSC_IDENTITY_AUTO_DISCOVERY=false` and has no certificate), so SmartScreen warns on Windows (see [INSTALL.md](INSTALL.md)).

Sizes on Linux: `build/python` ~500 MB, `build/web` ~24 MB, the AppImage ~285 MB.

To try a built AppImage without touching your profile: `HOMEFEED_USER_DATA_DIR=/tmp/homefeed-appimage-test ./build/release/Homefeed-<version>-x86_64.AppImage` (with `APPIMAGE_EXTRACT_AND_RUN=1` where FUSE isn't available). In extract-and-run mode every launch of the same AppImage unpacks into the same `$TMPDIR/appimage_extracted_<digest>` and deletes it on exit, so a second launch (which only shows the running instance's window) waits, windowless, until the running instance exits instead of deleting its files (see `src/main/appimage.ts`).

## Releasing

The app's version is `version` in this package's `package.json` (starting at 0.1.0). To release:

1. Bump `version` (e.g. 0.2.0) and commit.
2. Tag the commit `desktop-v0.2.0` and push the tag. The tag must match the version; the workflow fails otherwise.
3. The `Desktop release` workflow creates a draft release `v0.2.0` in this repo, builds both installers and uploads them (with `latest.yml`, `latest-linux.yml` and the blockmaps), then publishes the release. Installed apps pick it up within 6 hours or at their next start.

A manual run of the workflow (Actions → Desktop release → Run workflow) builds both installers as workflow artifacts and publishes nothing.

### Where releases go

Releases are published to this repo (`0xZ0uk/lenstube`) by the workflow's built-in `GITHUB_TOKEN`; nothing to set up. The repo is private, so the Releases tab and downloads are only visible to people with access to it (share installers with others some other way). electron-updater reads releases anonymously, so on a private repo an install's update check gets a 404: logged, harmless, and updating means installing the new version by hand. The repo is named in one place, `RELEASES_REPO` in `electron-builder.config.mjs` (`HOMEFEED_RELEASES_REPO` overrides it at build time); it's baked into each build's `resources/app-update.yml`, so changing it only affects builds made afterwards.
