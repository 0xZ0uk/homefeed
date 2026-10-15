import { describe, expect, it } from "vitest";

import {
  SIMILAR_EMPTY,
  similarButtonLabel,
  similarStatus,
  similarView,
} from "./similar";

describe("similarView", () => {
  it("is idle until the button is pressed, whatever is cached", () => {
    expect(similarView(false, { count: null, failed: false })).toBe("idle");
    expect(similarView(false, { count: 8, failed: false })).toBe("idle");
  });

  it("loads, then shows what came back", () => {
    expect(similarView(true, { count: null, failed: false })).toBe("loading");
    expect(similarView(true, { count: 3, failed: false })).toBe("found");
    expect(similarView(true, { count: 0, failed: false })).toBe("empty");
  });

  it("fails only when nothing is held to show", () => {
    expect(similarView(true, { count: null, failed: true })).toBe("failed");
    expect(similarView(true, { count: 3, failed: true })).toBe("found");
  });
});

describe("similarButtonLabel", () => {
  it("asks, waits, and asks again after a failure", () => {
    expect(similarButtonLabel("idle")).toBe("Find more like this");
    expect(similarButtonLabel("loading")).toBe("Finding…");
    expect(similarButtonLabel("failed")).toBe("Try again");
  });
});

describe("similarStatus", () => {
  it("counts what was found", () => {
    expect(similarStatus("found", 8)).toBe("Found 8 videos like this one.");
    expect(similarStatus("found", 1)).toBe("Found 1 video like this one.");
  });

  it("explains an empty answer and says nothing before or after trouble", () => {
    expect(similarStatus("empty", 0)).toBe(SIMILAR_EMPTY);
    expect(similarStatus("loading", 0)).toBe("Looking for similar videos…");
    expect(similarStatus("idle", 0)).toBe("");
    expect(similarStatus("failed", 0)).toBe("");
  });
});
