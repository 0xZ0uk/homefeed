import { globalIgnores } from "eslint/config";
import { config } from "@repo/eslint-config/react-internal";

/** @type {import("eslint").Linter.Config[]} */
export default [
  ...config,
  globalIgnores([
    ".output/**",
    ".tanstack/**",
    ".nitro/**",
    "src/routeTree.gen.ts",
  ]),
];
