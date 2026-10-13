#!/usr/bin/env node
/**
 * Builds `build/python/`: a standalone CPython (python-build-standalone, the
 * `install_only_stripped` build uv installs) with homefeed-api and its locked production
 * dependencies installed into its own site-packages, non-editable. electron-builder ships
 * it as `resources/python/` (see README.md, "Runtime layout").
 *
 *   node scripts/bundle-python.mjs
 *
 * Needs uv on PATH. Builds for the host platform only (no cross-builds). The interpreter is
 * pinned by PYTHON_VERSION below together with the uv version (uv knows the release and
 * sha256 of every build it installs; pin uv in CI); the dependencies by uv.lock.
 */
import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, readdirSync, rmSync, lstatSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PYTHON_VERSION = "3.13.16";

const desktopDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(desktopDir, "..", "..");
const buildDir = join(desktopDir, "build");
const outDir = join(buildDir, "python");
const workDir = join(buildDir, "python-work");
const windows = process.platform === "win32";

function run(command, args, options = {}) {
  console.log(`$ ${command} ${args.join(" ")}`);
  const result = spawnSync(command, args, {
    stdio: "inherit",
    cwd: repoRoot,
    ...options,
  });
  if (result.status !== 0) {
    throw new Error(
      `${command} failed (${result.error?.message ?? `exit ${result.status}`})`,
    );
  }
}

function dirSize(path) {
  const stat = lstatSync(path, { throwIfNoEntry: false });
  if (!stat) return 0;
  if (!stat.isDirectory()) return stat.size;
  return readdirSync(path).reduce(
    (total, name) => total + dirSize(join(path, name)),
    0,
  );
}

/** Deletes every directory or file under `root` for which `match(name, path)` is true. */
function prune(root, match) {
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (match(entry.name, path, entry.isDirectory())) {
      rmSync(path, { recursive: true, force: true });
    } else if (entry.isDirectory() && !entry.isSymbolicLink()) {
      prune(path, match);
    }
  }
}

rmSync(outDir, { recursive: true, force: true });
rmSync(workDir, { recursive: true, force: true });
mkdirSync(workDir, { recursive: true });

// 1. The interpreter: let uv download and verify it into a scratch dir, then copy the
// installation (`cpython-<version>-<platform>/`) to build/python.
const installDir = join(workDir, "install");
run("uv", [
  "python",
  "install",
  `cpython-${PYTHON_VERSION}`,
  "--install-dir",
  installDir,
  "--no-bin",
  ...(windows ? ["--no-registry"] : []),
]);
const [installed] = readdirSync(installDir).filter((name) =>
  name.startsWith(`cpython-${PYTHON_VERSION}-`),
);
if (!installed)
  throw new Error(`No cpython-${PYTHON_VERSION} in ${installDir}`);
cpSync(join(installDir, installed), outDir, {
  recursive: true,
  verbatimSymlinks: true,
});
const python = windows
  ? join(outDir, "python.exe")
  : join(outDir, "bin", "python3");
const minor = PYTHON_VERSION.split(".").slice(0, 2).join(".");
const sitePackages = windows
  ? join(outDir, "Lib", "site-packages")
  : join(outDir, "lib", `python${minor}`, "site-packages");
const stdlib = dirname(sitePackages);
// uv marks the interpreters it manages as externally managed; this copy is ours.
rmSync(join(stdlib, "EXTERNALLY-MANAGED"), { force: true });

// 2. Third-party dependencies, exactly as locked (with hashes), for this platform.
const requirements = join(workDir, "requirements.txt");
run("uv", [
  "export",
  "--frozen",
  "--no-dev",
  "--package",
  "homefeed-api",
  "--no-emit-workspace",
  "--format",
  "requirements-txt",
  "--output-file",
  requirements,
  "--quiet",
]);
const pipInstall = [
  "pip",
  "install",
  "--python",
  python,
  "--link-mode",
  "copy",
  "--no-config",
];
run("uv", [...pipInstall, "--require-hashes", "--requirement", requirements]);

// 3. The workspace packages, built as wheels and installed non-editable.
const wheels = join(workDir, "wheels");
for (const name of ["homefeed-core", "homefeed-worker", "homefeed-api"]) {
  run("uv", [
    "build",
    "--package",
    name,
    "--wheel",
    "--out-dir",
    wheels,
    "--quiet",
  ]);
}
run("uv", [
  ...pipInstall,
  "--no-deps",
  ...readdirSync(wheels)
    .filter((name) => name.endsWith(".whl"))
    .map((name) => join(wheels, name)),
]);

// 4. Drop what the app never runs: test suites, the IDE and Tk, headers, type stubs,
// console scripts, pip (the yt-dlp updater fetches wheels itself), and the old bytecode
// (step 5 compiles everything again).
prune(sitePackages, (name, _path, isDir) =>
  isDir
    ? name === "tests" || name === "pip" || /^pip-.*\.dist-info$/.test(name)
    : name.endsWith(".pyi"),
);
prune(stdlib, (name, _path, isDir) => isDir && name === "__pycache__");
for (const name of [
  "test",
  "idlelib",
  "tkinter",
  "turtledemo",
  "ensurepip",
  "__phello__",
  "turtle.py",
]) {
  rmSync(join(stdlib, name), { recursive: true, force: true });
}
for (const name of ["include", "share", "tcl", "Scripts"]) {
  rmSync(join(outDir, name), { recursive: true, force: true });
}
if (!windows) {
  // bin/python3.13 is statically linked: libpython is only for embedding.
  for (const name of readdirSync(join(outDir, "lib"))) {
    if (
      /^(libtcl|libtk|libpython|tcl\d|tk\d|itcl|thread\d|pkgconfig)/.test(name)
    ) {
      rmSync(join(outDir, "lib", name), { recursive: true, force: true });
    }
  }
  for (const name of readdirSync(join(outDir, "bin"))) {
    if (!["python", "python3", `python${minor}`].includes(name)) {
      rmSync(join(outDir, "bin", name), { force: true });
    }
  }
}
const extensions = windows ? join(outDir, "DLLs") : join(stdlib, "lib-dynload");
prune(extensions, (name) => /^(_tkinter|tcl\d|tk\d)/.test(name));

// 5. Bytecode for everything, checked by hash, not by timestamp: resources/python is
// read-only in the AppImage (nothing can be cached at runtime), and copying into the
// installer doesn't keep mtimes. "unchecked-hash" never looks at the sources again; the
// bundle is never edited after this.
run(python, [
  "-I",
  "-m",
  "compileall",
  "-q",
  "-j",
  "0",
  "--invalidation-mode",
  "unchecked-hash",
  stdlib,
]);

// 6. Smoke test: the app and its native extensions import from the bundle alone.
const scratch = join(tmpdir(), `homefeed-bundle-check-${process.pid}`);
mkdirSync(scratch, { recursive: true });
try {
  run(
    python,
    [
      "-I",
      "-c",
      "import homefeed_api.main, lightgbm, sqlite_vec, onnxruntime, fastembed, yt_dlp, yt_dlp_ejs, uvicorn; " +
        "import sqlite3; c = sqlite3.connect(':memory:'); c.enable_load_extension(True); sqlite_vec.load(c); " +
        "print('bundle ok:', yt_dlp.version.__version__, 'sqlite-vec', c.execute('select vec_version()').fetchone()[0])",
    ],
    {
      cwd: scratch,
      env: {
        ...process.env,
        DATA_DIR: scratch,
        DATABASE_PATH: join(scratch, "homefeed.sqlite"),
        HOMEFEED_NO_DOTENV: "1",
      },
    },
  );
} finally {
  rmSync(scratch, { recursive: true, force: true });
}

rmSync(workDir, { recursive: true, force: true });
console.log(`build/python: ${(dirSize(outDir) / 1024 / 1024).toFixed(0)} MB`);
