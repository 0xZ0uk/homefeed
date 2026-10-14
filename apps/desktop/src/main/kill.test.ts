import { spawn } from "node:child_process";

import { describe, expect, it } from "vitest";

import { killPlan, killTree, spawnDetached } from "./kill.js";

describe("killPlan", () => {
  it("uses taskkill on the whole tree on Windows", () => {
    expect(killPlan("win32", 1234)).toEqual({
      kind: "taskkill",
      command: "taskkill",
      args: ["/pid", "1234", "/T", "/F"],
    });
    expect(spawnDetached("win32")).toBe(false);
  });

  it("signals the process group elsewhere, SIGTERM then SIGKILL", () => {
    for (const platform of ["linux", "darwin"] as const) {
      expect(killPlan(platform, 1234)).toEqual({
        kind: "group",
        pgid: 1234,
        graceful: "SIGTERM",
        forceful: "SIGKILL",
      });
      expect(spawnDetached(platform)).toBe(true);
    }
  });
});

function isAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

describe.skipIf(process.platform === "win32")("killTree", () => {
  it("kills a detached child and its grandchildren, forcing past an ignored SIGTERM", async () => {
    // A shell that ignores SIGTERM and starts a grandchild, printing its pid.
    const child = spawn(
      "sh",
      ["-c", "trap '' TERM; sleep 60 & echo $!; wait"],
      {
        detached: true,
        stdio: ["ignore", "pipe", "ignore"],
      },
    );
    const grandchild = await new Promise<number>((resolve) =>
      child.stdout.once("data", (data: Buffer) =>
        resolve(Number(data.toString().trim())),
      ),
    );
    const exited = new Promise((resolve) => child.on("exit", resolve));
    expect(isAlive(grandchild)).toBe(true);

    await killTree(child.pid!, exited, { timeoutMs: 300 });

    expect(child.exitCode !== null || child.signalCode !== null).toBe(true);
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(isAlive(grandchild)).toBe(false);
  });
});
