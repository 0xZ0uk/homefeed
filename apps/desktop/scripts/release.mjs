#!/usr/bin/env node
/**
 * Releases the desktop app: bumps the minor version in this package's package.json
 * (0.1.0 → 0.2.0), commits it, pushes master, then tags the commit `desktop-v<version>`
 * and pushes the tag, which starts the "Desktop release" workflow (see README.md,
 * "Releasing").
 *
 *   nub run release:desktop               (from the repo root)
 *   nub run release:desktop --dry-run     (print what would happen, change nothing)
 *
 * Refuses to run unless on master, with a clean working tree, up to date with origin.
 */
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const dryRun = process.argv.includes("--dry-run");
const packageJsonPath = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "package.json",
);

function git(...args) {
  return execFileSync("git", args, { encoding: "utf8" }).trim();
}

function run(...args) {
  console.log(`$ git ${args.join(" ")}`);
  if (!dryRun) execFileSync("git", args, { stdio: "inherit" });
}

function fail(message) {
  console.error(`release: ${message}`);
  process.exit(1);
}

const root = git("rev-parse", "--show-toplevel");
process.chdir(root);

const branch = git("branch", "--show-current");
if (branch !== "master")
  fail(`on branch ${branch || "(detached)"}; switch to master first`);
if (git("status", "--porcelain"))
  fail("the working tree has changes; commit or stash them first");

git("fetch", "--quiet", "--tags", "origin", "master");
if (git("rev-parse", "HEAD") !== git("rev-parse", "origin/master")) {
  fail("master isn't the same as origin/master; pull or push first");
}

const source = readFileSync(packageJsonPath, "utf8");
const current = JSON.parse(source).version;
const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(current);
if (!match) fail(`can't bump version "${current}" (expected x.y.z)`);
const next = `${match[1]}.${Number(match[2]) + 1}.0`;
const tag = `desktop-v${next}`;

if (git("tag", "--list", tag)) fail(`tag ${tag} already exists`);

console.log(
  `Releasing Homefeed ${current} → ${next}${dryRun ? " (dry run)" : ""}\n`,
);

// Replace only the version line, keeping the file's formatting.
const updated = source.replace(/("version":\s*)"[^"]*"/, `$1"${next}"`);
const file = relative(root, packageJsonPath);
if (!dryRun) writeFileSync(packageJsonPath, updated);
console.log(`Set version ${next} in ${file}`);

run("add", file);
run("commit", "--quiet", "-m", `Desktop: release ${next}`);
run("push", "origin", "master");
run("tag", tag);
run("push", "origin", tag);

console.log(
  `\nPushed ${tag}. The "Desktop release" workflow builds the installers and publishes release v${next}:`,
);
console.log(
  `  gh run watch $(gh run list -w "Desktop release" -L 1 --json databaseId -q '.[0].databaseId')`,
);
