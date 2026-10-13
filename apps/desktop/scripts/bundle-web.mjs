#!/usr/bin/env node
/**
 * Builds `build/web/`: apps/web's production build plus a flat `node_modules/` with only
 * what the server build imports at runtime, and srvx. electron-builder ships it as
 * `resources/web/` (see README.md, "Runtime layout").
 *
 *   node scripts/bundle-web.mjs      (after `vite build` in apps/web)
 *
 * The TanStack Start server build bundles most of its code; what it leaves external
 * (react, the TanStack routers, UI libraries) is found by scanning its imports. Each
 * external package and its production dependencies are copied from the workspace's
 * node_modules (nub links them from its store) as real directories: hoisted to the top
 * where versions agree, nested under the dependent package where they don't, as npm
 * would. Nothing in web/ is a symlink.
 */
import {
  cpSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  realpathSync,
  rmSync,
} from "node:fs";
import { builtinModules } from "node:module";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const desktopDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const webDir = resolve(desktopDir, "..", "web");
const outDir = join(desktopDir, "build", "web");
const outModules = join(outDir, "node_modules");

// Files no running server needs.
const SKIPPED_FILE = /\.(map|d\.ts|d\.mts|d\.cts|md|markdown)$/i;
// Big packages of which the server build imports a single file (keep only that).
const ONLY_FILES = {
  "shaka-player": ["package.json", "LICENSE", "dist/shaka-player.dash.js"],
};

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function filesUnder(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    return entry.isDirectory() ? filesUnder(path) : [path];
  });
}

/** `name` of a bare import specifier: `@scope/pkg/sub` → `@scope/pkg`. */
function packageName(specifier) {
  const parts = specifier.split("/");
  return specifier.startsWith("@") ? parts.slice(0, 2).join("/") : parts[0];
}

/** Packages the server build imports (static and literal dynamic imports). */
function serverExternals() {
  const builtins = new Set(builtinModules);
  const names = new Set();
  // A bare package specifier after `from` / `import` / `import(`.
  const importRe =
    /\b(?:from|import)\s*\(?\s*["']((?:@[a-z0-9][\w.-]*\/)?[a-z0-9][\w.-]*(?:\/[\w./@-]*)?|node:[\w/]+)["']/g;
  for (const file of filesUnder(join(webDir, "dist", "server"))) {
    if (!/\.m?js$/.test(file)) continue;
    for (const [, specifier] of readFileSync(file, "utf8").matchAll(importRe)) {
      if (specifier.startsWith("node:") || specifier.startsWith("#")) continue;
      const name = packageName(specifier);
      if (!builtins.has(name)) names.add(name);
    }
  }
  return [...names].sort();
}

/** Node's directory lookup for `name` from `fromDir` (ignores "exports"); real path or null. */
function findPackage(name, fromDir) {
  for (let dir = fromDir; ; dir = dirname(dir)) {
    const candidate = join(dir, "node_modules", name);
    if (existsSync(join(candidate, "package.json")))
      return realpathSync(candidate);
    if (dirname(dir) === dir) return null;
  }
}

// Real source dir of each package placed in web/node_modules, by its path there.
const placed = new Map();

/** Where Node would find `name` from a package placed at `fromPath` (null: nowhere yet). */
function resolvePlaced(name, fromPath) {
  for (let dir = fromPath; ; dir = dirname(dir)) {
    const candidate = join(dir, "node_modules", name);
    if (placed.has(candidate)) return candidate;
    if (dir === outDir) return null;
  }
}

/** Places `name` (resolved from `sourceFrom`) so that it's found from `fromPath`. */
function place(name, sourceFrom, fromPath, optional) {
  // Type declarations only (an optional peer of react's packages).
  if (name.startsWith("@types/")) return;
  const source = findPackage(name, sourceFrom);
  if (!source) {
    if (optional) return;
    throw new Error(`Can't find ${name} from ${sourceFrom}`);
  }
  const existing = resolvePlaced(name, fromPath);
  if (existing && placed.get(existing) === source) return;
  const target = existing
    ? join(fromPath, "node_modules", name)
    : join(outModules, name);
  if (target === existing) {
    throw new Error(`${name}: two versions needed at ${target}`);
  }
  placed.set(target, source);
  const pkg = readJson(join(source, "package.json"));
  const deps = [
    ...Object.keys(pkg.dependencies ?? {}).map((dep) => [dep, false]),
    ...Object.keys(pkg.optionalDependencies ?? {}).map((dep) => [dep, true]),
    // Peers resolve from the package's own location in the store; only installed ones.
    ...Object.keys(pkg.peerDependencies ?? {}).map((dep) => [dep, true]),
  ];
  for (const [dep, isOptional] of deps) place(dep, source, target, isOptional);
}

if (!existsSync(join(webDir, "dist", "server", "server.js"))) {
  throw new Error(
    `No web build in ${webDir}/dist: run \`nub run build\` first.`,
  );
}
rmSync(outDir, { recursive: true, force: true });
mkdirSync(outDir, { recursive: true });
cpSync(join(webDir, "package.json"), join(outDir, "package.json"));
cpSync(join(webDir, "dist"), join(outDir, "dist"), { recursive: true });

const externals = serverExternals();
console.log(`server build imports: ${externals.join(", ")}`);
for (const name of externals) place(name, webDir, outDir, false);
// srvx runs the server; pinned through this package's devDependency (and nub.lock).
place("srvx", desktopDir, outDir, false);

for (const [target, source] of placed) {
  const only = ONLY_FILES[readJson(join(source, "package.json")).name];
  if (only) {
    for (const file of only) cpSync(join(source, file), join(target, file));
    continue;
  }
  cpSync(source, target, {
    recursive: true,
    dereference: true,
    filter: (path) => {
      const rel = relative(source, path);
      // Dependencies are placed separately; skip whatever the store nests in here.
      if (rel.split(sep).includes("node_modules")) return false;
      return !SKIPPED_FILE.test(path) || /license/i.test(path);
    },
  });
}

for (const file of filesUnder(outDir)) {
  if (lstatSync(file).isSymbolicLink())
    throw new Error(`symlink left: ${file}`);
}
const size = filesUnder(outDir).reduce(
  (total, file) => total + lstatSync(file).size,
  0,
);
console.log(
  `build/web: ${placed.size} packages, ${(size / 1024 / 1024).toFixed(1)} MB`,
);
