import { createRequire } from "node:module";
import pluginReactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import { config as baseConfig } from "./base.js";

const require = createRequire(import.meta.url);

/**
 * A custom ESLint configuration for libraries and apps that use React.
 *
 * @type {import("eslint").Linter.Config[]} */
export const config = [
  ...baseConfig,
  {
    languageOptions: {
      globals: {
        ...globals.serviceworker,
        ...globals.browser,
      },
    },
  },
  {
    // Babel 8's TypeScript preset no longer enables JSX for .tsx files on its own.
    files: ["**/*.{jsx,tsx}"],
    languageOptions: {
      parserOptions: {
        babelOptions: {
          plugins: [require.resolve("@babel/plugin-syntax-jsx")],
        },
      },
    },
  },
  pluginReactHooks.configs.flat.recommended,
];
