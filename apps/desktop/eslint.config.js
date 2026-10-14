import { globalIgnores } from "eslint/config";
import globals from "globals";
import { config } from "@repo/eslint-config/base";

/** @type {import("eslint").Linter.Config[]} */
export default [
  ...config,
  // Packaging inputs and outputs (bundle scripts, electron-builder).
  globalIgnores(["build/**"]),
  {
    // Packaging scripts run on Node.
    files: ["scripts/**/*.mjs", "electron-builder.config.mjs"],
    languageOptions: { globals: globals.node },
  },
];
