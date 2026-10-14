/**
 * The runtime layout contract: where the shell finds the Python API and the web server,
 * in dev (`electron .` from the repo) and packaged (`app.isPackaged`) mode, and how it
 * launches them. The packaging step must produce exactly the packaged layout described
 * here and in README.md ("Runtime layout").
 *
 * Pure: everything Electron-specific comes in through `LayoutInput`.
 */
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

export interface LayoutInput {
  isPackaged: boolean;
  platform: NodeJS.Platform;
  /** `app.getAppPath()`: apps/desktop in dev. */
  appPath: string;
  /** `process.resourcesPath`: the packaged app's resources directory. */
  resourcesPath: string;
  /** Dev only: srvx's bin script, resolved from this workspace's devDependencies. */
  devSrvxBin?: string;
}

export interface Layout {
  mode: "dev" | "packaged";
  /** Python interpreter with homefeed-api (and its dependencies) installed. */
  python: string;
  /**
   * The web server's root and working directory, laid out like apps/web after
   * `vite build`: `package.json` ("type": "module"), `dist/server/server.js` (+ assets),
   * `dist/client/**`, and production dependencies resolvable from `dist/server`.
   */
  webRoot: string;
  /** srvx's CLI (`srvx/bin/srvx.mjs`), run with Electron's Node. */
  srvxBin: string;
}

/** Entry and static dir passed to srvx, relative to `webRoot` (as in the Dockerfile). */
export const WEB_ENTRY = "dist/server/server.js";
const WEB_STATIC = "../client"; // srvx resolves --static against the entry's directory

export function resolveLayout(input: LayoutInput): Layout {
  const { platform } = input;
  if (input.isPackaged) {
    const resources = input.resourcesPath;
    const pythonDir = join(resources, "python");
    const webRoot = join(resources, "web");
    return {
      mode: "packaged",
      python:
        platform === "win32"
          ? join(pythonDir, "python.exe")
          : join(pythonDir, "bin", "python3"),
      webRoot,
      srvxBin: join(webRoot, "node_modules", "srvx", "bin", "srvx.mjs"),
    };
  }
  // Dev: the repo's uv venv (`uv sync --all-packages`) and apps/web's build output.
  const repoRoot = resolve(input.appPath, "..", "..");
  const venv = join(repoRoot, ".venv");
  return {
    mode: "dev",
    python:
      platform === "win32"
        ? join(venv, "Scripts", "python.exe")
        : join(venv, "bin", "python"),
    webRoot: join(repoRoot, "apps", "web"),
    srvxBin: input.devSrvxBin ?? "",
  };
}

/** What's missing from `layout`, as messages saying how to fix it (empty when complete). */
export function missingLayoutParts(
  layout: Layout,
  exists: (path: string) => boolean = existsSync,
): string[] {
  const dev = layout.mode === "dev";
  const missing: string[] = [];
  if (!exists(layout.python)) {
    missing.push(
      dev
        ? `Python not found at ${layout.python}: run \`uv sync --all-packages\` in the repo.`
        : `Python not found at ${layout.python}: the app is incomplete, reinstall it.`,
    );
  }
  if (!exists(join(layout.webRoot, WEB_ENTRY))) {
    missing.push(
      dev
        ? `Web build not found in ${layout.webRoot}: run \`nub run build\` in the repo.`
        : `Web server not found in ${layout.webRoot}: the app is incomplete, reinstall it.`,
    );
  }
  if (!layout.srvxBin || !exists(layout.srvxBin)) {
    missing.push(`srvx not found at ${layout.srvxBin || "(unresolved)"}.`);
  }
  return missing;
}

export interface Command {
  command: string;
  args: string[];
  cwd: string;
}

/**
 * The API: uvicorn serving `homefeed_api.main:app` on 127.0.0.1 (as the Docker image does,
 * plus `-I`: ignore PYTHON* env vars and the user's site-packages, so nothing outside the
 * bundled interpreter leaks in; `-u`/`-X utf8` because `-I` also drops PYTHONUNBUFFERED and
 * PYTHONUTF8). Its working directory is the data dir; `.env` files are never read
 * (`HOMEFEED_NO_DOTENV`, see env.ts), so neither the repo's nor a stray `~/.env` applies.
 */
export function apiCommand(
  layout: Layout,
  port: number,
  dataDir: string,
): Command {
  return {
    command: layout.python,
    args: [
      "-I",
      "-u",
      "-X",
      "utf8",
      "-m",
      "uvicorn",
      "homefeed_api.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
      // Playback proxies every media segment through the API; don't log each request.
      "--no-access-log",
    ],
    cwd: dataDir,
  };
}

/** The web server: srvx serving the TanStack Start build, run with `nodePath` (Electron). */
export function webCommand(layout: Layout, nodePath: string): Command {
  return {
    command: nodePath,
    args: [
      layout.srvxBin,
      "serve",
      "--prod",
      `--entry=${WEB_ENTRY}`,
      `--static=${WEB_STATIC}`,
    ],
    cwd: layout.webRoot,
  };
}
