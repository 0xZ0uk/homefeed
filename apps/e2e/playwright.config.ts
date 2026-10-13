import { defineConfig, devices } from "@playwright/test";

import {
  API_URL,
  APP_PASSWORD,
  AUTH_FILE,
  SESSION_SECRET,
  WEB_URL,
} from "./tests/env";

const webDir = new URL("../web/", import.meta.url).pathname;
const webPort = new URL(WEB_URL).port;

/**
 * End-to-end flows over the real web app and API, with the API on a fake
 * Gateway (`fake_api.py`) and a throwaway data dir. Tests share one database
 * and reset it first, so they run one at a time.
 */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: WEB_URL,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        storageState: AUTH_FILE,
      },
      dependencies: ["setup"],
    },
  ],
  webServer: [
    {
      name: "api",
      command: "uv run --package homefeed-api python fake_api.py",
      url: `${API_URL}/health`,
      env: { E2E_API_PORT: new URL(API_URL).port },
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "pipe",
      // SIGTERM (not the default SIGKILL) lets it delete its temp data dir.
      gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
    },
    {
      name: "web",
      command: `node_modules/.bin/vite dev --port ${webPort} --strictPort`,
      cwd: webDir,
      url: `${WEB_URL}/login`,
      env: { API_URL, APP_PASSWORD, SESSION_SECRET },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
