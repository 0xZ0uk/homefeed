import { describe, expect, it } from "vitest";

import { updateSupport } from "./updates.js";

describe("updateSupport", () => {
  it("never updates a dev build", () => {
    expect(
      updateSupport({ isPackaged: false, platform: "win32", env: {} }),
    ).toEqual({ enabled: false, reason: "not a packaged build" });
  });

  it("updates the Windows install", () => {
    expect(
      updateSupport({ isPackaged: true, platform: "win32", env: {} }),
    ).toEqual({ enabled: true });
  });

  it("updates on Linux only when running as an AppImage", () => {
    expect(
      updateSupport({
        isPackaged: true,
        platform: "linux",
        env: { APPIMAGE: "/home/u/Homefeed.AppImage" },
      }),
    ).toEqual({ enabled: true });
    expect(
      updateSupport({ isPackaged: true, platform: "linux", env: {} }),
    ).toEqual({ enabled: false, reason: "not running as an AppImage" });
  });

  it("doesn't update on other platforms", () => {
    expect(
      updateSupport({ isPackaged: true, platform: "darwin", env: {} }).enabled,
    ).toBe(false);
  });
});
