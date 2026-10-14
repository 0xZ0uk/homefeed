/**
 * Launching the AppImage again while it runs, in extract-and-run mode.
 *
 * Without FUSE (or with `--appimage-extract-and-run` / `APPIMAGE_EXTRACT_AND_RUN=1`, which
 * some desktop integrations put in the launcher), the AppImage runtime unpacks the app to
 * `$TMPDIR/appimage_extracted_<digest>` and, once the process it started exits, deletes
 * that directory (unless `NO_CLEANUP` is set). The directory depends only on the AppImage
 * file, so a second launch unpacks into, and then deletes, the directory the running
 * instance lives in: the second instance only hands over to the first (single-instance
 * lock) and exits at once, and its runtime removes the first instance's files. The first
 * keeps running on what it had already loaded, but every page it hadn't opened yet (code
 * split chunks of the web app) is gone: blank pages and 500s until it is restarted.
 *
 * So in that mode the second instance doesn't exit right away: it waits, windowless,
 * until the first one has, and only then lets its runtime clean up.
 */
import { readlinkSync } from "node:fs";
import { basename, join } from "node:path";

const EXTRACTED_PREFIX = "appimage_extracted_";
// Short: a launch right after the first instance quits unpacks into the same directory,
// which this one's runtime deletes when it exits.
export const PRIMARY_POLL_MS = 1_000;

/** Whether this process runs from an AppImage unpacked by extract-and-run (shared dir). */
export function isExtractAndRun(env: NodeJS.ProcessEnv): boolean {
  const appDir = env["APPDIR"];
  return Boolean(
    env["APPIMAGE"] && appDir && basename(appDir).startsWith(EXTRACTED_PREFIX),
  );
}

/**
 * The PID in a Chromium `SingletonLock` link target (`<hostname>-<pid>`, Linux), if the
 * lock is held on this host.
 */
export function parseSingletonLock(
  target: string,
  hostname: string,
): number | undefined {
  const separator = target.lastIndexOf("-");
  if (separator <= 0) return undefined;
  if (target.slice(0, separator) !== hostname) return undefined;
  const pid = Number(target.slice(separator + 1));
  return Number.isInteger(pid) && pid > 0 ? pid : undefined;
}

/** The PID of the instance holding the single-instance lock in `userData`, if known. */
export function lockHolderPid(
  userData: string,
  hostname: string,
): number | undefined {
  try {
    return parseSingletonLock(
      readlinkSync(join(userData, "SingletonLock")),
      hostname,
    );
  } catch {
    return undefined;
  }
}

export function isAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    // EPERM: it exists, but isn't ours.
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

/**
 * Calls `done` once `pid` has exited (checked every `intervalMs`). Returns a function that
 * stops waiting.
 */
export function whenExited(
  pid: number,
  done: () => void,
  options: { intervalMs?: number; alive?: (pid: number) => boolean } = {},
): () => void {
  const alive = options.alive ?? isAlive;
  const timer = setInterval(() => {
    if (alive(pid)) return;
    clearInterval(timer);
    done();
  }, options.intervalMs ?? PRIMARY_POLL_MS);
  return () => clearInterval(timer);
}
