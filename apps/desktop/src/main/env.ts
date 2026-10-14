/** Per-launch secrets and the environment of the API and web processes. */
import { randomBytes } from "node:crypto";
import { join } from "node:path";

/** A URL-safe random secret: 32 bytes, 43 characters (the web server needs at least 32). */
export function generateSecret(): string {
  return randomBytes(32).toString("base64url");
}

export interface DataPaths {
  dataDir: string;
  databasePath: string;
}

/** The data dir lives under `userData` (`app.getPath("userData")`). */
export function dataPaths(userData: string): DataPaths {
  const dataDir = join(userData, "data");
  return { dataDir, databasePath: join(dataDir, "homefeed.sqlite") };
}

// Variables from the parent environment that would point Python at another installation.
const PYTHON_ENV_DROPPED = ["PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"];

/**
 * The API's environment: the worker's jobs run in the API process, embeddings are local
 * (no key needed), and tagging defaults to OpenRouter, which is skipped until a key is
 * entered in Settings. User settings live in the database; these are only defaults.
 */
export function apiEnv(options: {
  base: NodeJS.ProcessEnv;
  paths: DataPaths;
  /** Electron's executable, which yt-dlp runs as Node (with ELECTRON_RUN_AS_NODE). */
  jsRuntime: string;
}): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...options.base };
  for (const name of PYTHON_ENV_DROPPED) delete env[name];
  return {
    ...env,
    DATA_DIR: options.paths.dataDir,
    DATABASE_PATH: options.paths.databasePath,
    RUN_WORKER_IN_API: "true",
    EMBEDDING_PROVIDER: "local",
    EMBEDDING_MODEL: "BAAI/bge-small-en-v1.5",
    LLM_PROVIDER: "openrouter",
    // yt-dlp breaks when YouTube changes; the app can't be rebuilt that quickly.
    YTDLP_AUTO_UPDATE: "true",
    HOMEFEED_JS_RUNTIME: options.jsRuntime,
    ELECTRON_RUN_AS_NODE: "1",
    // Never read a `.env` file: settings would pick up any at or above the data dir
    // (e.g. `~/.env`).
    HOMEFEED_NO_DOTENV: "1",
  };
}

/** The web server's environment: desktop auth mode, bound to 127.0.0.1. */
export function webEnv(options: {
  base: NodeJS.ProcessEnv;
  port: number;
  apiPort: number;
  desktopToken: string;
  sessionSecret: string;
}): NodeJS.ProcessEnv {
  return {
    ...options.base,
    ELECTRON_RUN_AS_NODE: "1",
    NODE_ENV: "production",
    // srvx colors its request log unless told not to; it goes to a file.
    NO_COLOR: "1",
    HOST: "127.0.0.1",
    PORT: String(options.port),
    API_URL: `http://127.0.0.1:${options.apiPort}`,
    HOMEFEED_MODE: "desktop",
    DESKTOP_TOKEN: options.desktopToken,
    SESSION_SECRET: options.sessionSecret,
  };
}

/** The URL that starts a session (see the web app's /desktop-auth) and opens `next`. */
export function desktopAuthUrl(
  webPort: number,
  token: string,
  next = "/",
): string {
  const url = new URL(`http://127.0.0.1:${webPort}/desktop-auth`);
  url.searchParams.set("token", token);
  url.searchParams.set("next", next);
  return url.toString();
}
