#!/usr/bin/env node
/**
 * Bundles the compiled main process (`dist/main/`, from `tsc`) and its one runtime
 * dependency, electron-updater, into `dist/bundle/main.js` for the packaged app. app.asar
 * then holds no node_modules (electron-builder can't read nub's store layout, and there's
 * nothing else to ship). Dev (`electron .`) keeps running the unbundled `dist/main/`.
 */
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const desktopDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");

await build({
  entryPoints: [join(desktopDir, "dist", "main", "main.js")],
  outfile: join(desktopDir, "dist", "bundle", "main.js"),
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node24",
  external: ["electron"],
  // electron-updater (CommonJS) `require`s Node built-ins, which ES modules don't have.
  banner: {
    js: 'import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);',
  },
  logLevel: "warning",
});
console.log("dist/bundle/main.js");
