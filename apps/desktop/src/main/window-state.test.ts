import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  DEFAULT_SIZE,
  initialBounds,
  loadWindowState,
  saveWindowState,
  type WindowState,
} from "./window-state.js";

const display = { x: 0, y: 0, width: 1920, height: 1040 };
const state: WindowState = {
  bounds: { x: 100, y: 50, width: 1000, height: 700 },
  maximized: true,
};

describe("window state file", () => {
  it("round-trips", () => {
    const path = join(
      mkdtempSync(join(tmpdir(), "homefeed-ws-")),
      "sub",
      "window-state.json",
    );
    saveWindowState(path, state);
    expect(loadWindowState(path)).toEqual(state);
  });

  it("ignores missing or malformed files", () => {
    const dir = mkdtempSync(join(tmpdir(), "homefeed-ws-"));
    expect(loadWindowState(join(dir, "nope.json"))).toBeNull();
    const bad = join(dir, "bad.json");
    writeFileSync(bad, '{"bounds":{"x":"1"},"maximized":false}');
    expect(loadWindowState(bad)).toBeNull();
    writeFileSync(bad, "not json");
    expect(loadWindowState(bad)).toBeNull();
  });
});

describe("initialBounds", () => {
  it("restores bounds that are on a display", () => {
    expect(initialBounds(state, [display])).toEqual(state.bounds);
  });

  it("falls back to the default size when the display is gone", () => {
    const offscreen = { ...state, bounds: { ...state.bounds, x: 2500 } };
    expect(initialBounds(offscreen, [display])).toEqual(DEFAULT_SIZE);
    // Only a sliver visible on the remaining display.
    const sliver = { ...state, bounds: { ...state.bounds, x: 1880 } };
    expect(initialBounds(sliver, [display])).toEqual(DEFAULT_SIZE);
    expect(initialBounds(null, [display])).toEqual(DEFAULT_SIZE);
  });

  it("accepts bounds on a second display", () => {
    const right = { x: 1920, y: 0, width: 2560, height: 1400 };
    const there = { ...state, bounds: { ...state.bounds, x: 2200 } };
    expect(initialBounds(there, [display, right])).toEqual(there.bounds);
  });
});
