import { mkdtempSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  isAlive,
  isExtractAndRun,
  lockHolderPid,
  parseSingletonLock,
  whenExited,
} from "./appimage.js";

describe("isExtractAndRun", () => {
  it("is true when the AppImage was unpacked by extract-and-run", () => {
    expect(
      isExtractAndRun({
        APPIMAGE: "/home/u/AppImages/homefeed.appimage",
        APPDIR: "/tmp/appimage_extracted_cf5712432f236729b8fa39e20adb261d",
      }),
    ).toBe(true);
  });

  it("is false for a FUSE mount (each launch gets its own) or outside an AppImage", () => {
    expect(
      isExtractAndRun({
        APPIMAGE: "/home/u/H.AppImage",
        APPDIR: "/tmp/.mount_HomefeAbC123",
      }),
    ).toBe(false);
    expect(
      isExtractAndRun({ APPDIR: "/tmp/appimage_extracted_cf5712432f" }),
    ).toBe(false);
    expect(isExtractAndRun({})).toBe(false);
  });
});

describe("parseSingletonLock", () => {
  it("reads the PID of a lock held on this host", () => {
    expect(parseSingletonLock("blackbox-4070965", "blackbox")).toBe(4070965);
    expect(parseSingletonLock("my-laptop-42", "my-laptop")).toBe(42);
  });

  it("ignores another host's lock and malformed targets", () => {
    expect(parseSingletonLock("other-42", "blackbox")).toBeUndefined();
    expect(parseSingletonLock("blackbox", "blackbox")).toBeUndefined();
    expect(parseSingletonLock("blackbox-x", "blackbox")).toBeUndefined();
    expect(parseSingletonLock("blackbox-0", "blackbox")).toBeUndefined();
  });
});

describe("lockHolderPid", () => {
  let dir: string | undefined;
  afterEach(() => {
    if (dir) rmSync(dir, { recursive: true, force: true });
    dir = undefined;
  });

  it("reads Chromium's SingletonLock link in userData", () => {
    dir = mkdtempSync(join(tmpdir(), "homefeed-lock-"));
    symlinkSync("host-1234", join(dir, "SingletonLock"));
    expect(lockHolderPid(dir, "host")).toBe(1234);
  });

  it("is undefined without a lock", () => {
    dir = mkdtempSync(join(tmpdir(), "homefeed-lock-"));
    expect(lockHolderPid(dir, "host")).toBeUndefined();
  });
});

describe("isAlive", () => {
  it("is true for this process", () => {
    expect(isAlive(process.pid)).toBe(true);
  });
});

describe("whenExited", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("waits while the process lives, then calls back once", () => {
    vi.useFakeTimers();
    let alive = true;
    const done = vi.fn();
    whenExited(42, done, { intervalMs: 1000, alive: () => alive });

    vi.advanceTimersByTime(5000);
    expect(done).not.toHaveBeenCalled();

    alive = false;
    vi.advanceTimersByTime(1000);
    vi.advanceTimersByTime(5000);
    expect(done).toHaveBeenCalledOnce();
  });
});
