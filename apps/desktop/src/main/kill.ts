/**
 * Killing a child process and everything it started (yt-dlp runs subprocesses, for one).
 *
 * Windows: children don't die with their parent and `kill()` only ends the direct child,
 * so `taskkill /T /F` ends the tree. Elsewhere children are spawned `detached` (their own
 * process group), and the whole group gets SIGTERM, then SIGKILL after a timeout.
 */
import { spawn, spawnSync } from "node:child_process";

export type KillPlan =
  | { kind: "taskkill"; command: string; args: string[] }
  | {
      kind: "group";
      pgid: number;
      graceful: NodeJS.Signals;
      forceful: NodeJS.Signals;
    };

export function killPlan(platform: NodeJS.Platform, pid: number): KillPlan {
  if (platform === "win32") {
    return {
      kind: "taskkill",
      command: "taskkill",
      args: ["/pid", String(pid), "/T", "/F"],
    };
  }
  return { kind: "group", pgid: pid, graceful: "SIGTERM", forceful: "SIGKILL" };
}

/** Whether to spawn children in their own process group (so the group can be killed). */
export function spawnDetached(platform: NodeJS.Platform): boolean {
  return platform !== "win32";
}

function signalGroup(pgid: number, signal: NodeJS.Signals): void {
  try {
    process.kill(-pgid, signal);
  } catch {
    // ESRCH: the group is already gone.
  }
}

/**
 * Kill the tree rooted at `pid`; `exited` resolves when the direct child has exited. Waits
 * `timeoutMs` after the graceful signal before forcing.
 */
export async function killTree(
  pid: number,
  exited: Promise<unknown>,
  { platform = process.platform, timeoutMs = 5000 } = {},
): Promise<void> {
  const plan = killPlan(platform, pid);
  if (plan.kind === "taskkill") {
    await new Promise<void>((resolve) => {
      const proc = spawn(plan.command, plan.args, {
        windowsHide: true,
        stdio: "ignore",
      });
      proc.on("error", () => resolve());
      proc.on("exit", () => resolve());
    });
    await Promise.race([exited, delay(timeoutMs)]);
    return;
  }
  signalGroup(plan.pgid, plan.graceful);
  const timedOut = await Promise.race([
    exited.then(() => false),
    delay(timeoutMs).then(() => true),
  ]);
  // Also after a clean exit: the leader may leave grandchildren behind in the group.
  signalGroup(plan.pgid, plan.forceful);
  if (timedOut) await Promise.race([exited, delay(1000)]);
}

/** Synchronous best effort, for `process.on("exit")` when the shell itself is going down. */
export function killTreeSync(
  pid: number,
  platform: NodeJS.Platform = process.platform,
): void {
  const plan = killPlan(platform, pid);
  if (plan.kind === "taskkill") {
    spawnSync(plan.command, plan.args, { windowsHide: true, stdio: "ignore" });
  } else {
    signalGroup(plan.pgid, plan.forceful);
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms).unref());
}
