import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { RotatingLog } from "./log.js";
import { findFreePort } from "./ports.js";
import { redact, RestartPolicy, Service } from "./service.js";

describe("redact", () => {
  it("masks secrets in child output", () => {
    const line = Buffer.from("GET /desktop-auth?token=s3cr3t&next=%2F [303]\n");
    expect(redact(line, ["s3cr3t"])).toBe(
      "GET /desktop-auth?token=<redacted>&next=%2F [303]\n",
    );
    expect(redact(line)).toBe(line);
  });
});

describe("RestartPolicy", () => {
  it("allows maxRestarts within the window, then refuses", () => {
    const policy = new RestartPolicy(2, 1000);
    expect(policy.tryRestart(0)).toBe(true);
    expect(policy.tryRestart(10)).toBe(true);
    expect(policy.tryRestart(20)).toBe(false);
    // The first restart has left the window.
    expect(policy.tryRestart(1001)).toBe(true);
    expect(policy.tryRestart(1002)).toBe(false);
  });

  it("starts over after reset", () => {
    const policy = new RestartPolicy(1, 1000);
    expect(policy.tryRestart(0)).toBe(true);
    expect(policy.tryRestart(1)).toBe(false);
    policy.reset();
    expect(policy.tryRestart(2)).toBe(true);
  });
});

describe("Service", () => {
  const logDir = () => mkdtempSync(join(tmpdir(), "homefeed-service-"));

  it("starts a server, waits for it, logs its output and stops it", async () => {
    const port = await findFreePort();
    const dir = logDir();
    const service = new Service(
      {
        name: "test",
        command: process.execPath,
        args: [
          "-e",
          `console.log("hello from child");
           require("node:http").createServer((_, res) => res.end("ok")).listen(${port}, "127.0.0.1");`,
        ],
        cwd: dir,
        env: { ...process.env, ELECTRON_RUN_AS_NODE: "1" },
        readyUrl: `http://127.0.0.1:${port}/`,
        isReady: (response) => response.ok,
      },
      new RotatingLog(dir, "test"),
    );
    let crashed = false;
    service.onCrash = () => (crashed = true);
    service.start();
    await service.waitUntilReady(10_000);
    expect(service.running).toBe(true);
    await service.stop();
    expect(service.running).toBe(false);
    expect(crashed).toBe(false);
    expect(readFileSync(join(dir, "test.log"), "utf8")).toContain(
      "hello from child",
    );
  });

  it("fails fast when the process exits while starting, and reports the crash", async () => {
    const dir = logDir();
    const service = new Service(
      {
        name: "broken",
        command: process.execPath,
        args: ["-e", "process.exit(3)"],
        cwd: dir,
        env: process.env,
        readyUrl: "http://127.0.0.1:9/",
        isReady: () => true,
      },
      new RotatingLog(dir, "broken"),
    );
    const crash = new Promise<number | null>(
      (resolve) => (service.onCrash = (code) => resolve(code)),
    );
    service.start();
    await expect(service.waitUntilReady(10_000)).rejects.toThrow(
      "broken exited while starting",
    );
    expect(await crash).toBe(3);
  });

  it("times out when nothing answers", async () => {
    const port = await findFreePort();
    const dir = logDir();
    const service = new Service(
      {
        name: "slow",
        command: process.execPath,
        args: ["-e", "setTimeout(() => {}, 60_000)"],
        cwd: dir,
        env: process.env,
        readyUrl: `http://127.0.0.1:${port}/`,
        isReady: () => true,
      },
      new RotatingLog(dir, "slow"),
    );
    service.start();
    await expect(service.waitUntilReady(300)).rejects.toThrow("didn't start");
    await service.stop();
  });
});
