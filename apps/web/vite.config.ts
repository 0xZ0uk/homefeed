import { defineConfig, loadEnv } from "vite";
import { devtools } from "@tanstack/devtools-vite";

import { tanstackStart } from "@tanstack/react-start/plugin/vite";

import viteReact from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const repoRoot = new URL("../..", import.meta.url).pathname;

const config = defineConfig(({ command, mode }) => {
  if (command === "serve") {
    // Server code reads `process.env` (API_URL, APP_PASSWORD, SESSION_SECRET).
    // In dev, fill it from the repo-root `.env` shared with the Python apps;
    // variables already set in the environment win.
    for (const [key, value] of Object.entries(loadEnv(mode, repoRoot, ""))) {
      process.env[key] ??= value;
    }
  }

  return {
    resolve: { tsconfigPaths: true },
    plugins: [devtools(), tailwindcss(), tanstackStart(), viteReact()],
  };
});

export default config;
