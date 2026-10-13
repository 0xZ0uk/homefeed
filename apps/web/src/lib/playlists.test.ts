import { describe, expect, it } from "vitest";

import {
  checkPlaylistDescription,
  checkPlaylistId,
  checkPlaylistName,
  checkPosition,
  describeItemCount,
  moveItem,
  parsePlaylistId,
  stepPosition,
} from "./playlists";

describe("checkPlaylistName", () => {
  it("trims names", () => {
    expect(checkPlaylistName("  Watch later ")).toEqual({
      ok: true,
      name: "Watch later",
    });
  });

  it("rejects blank, long and non-string names", () => {
    expect(checkPlaylistName("   ").ok).toBe(false);
    expect(checkPlaylistName(42).ok).toBe(false);
    expect(checkPlaylistName("x".repeat(101)).ok).toBe(false);
    expect(checkPlaylistName("x".repeat(100)).ok).toBe(true);
  });
});

describe("checkPlaylistDescription", () => {
  it("trims and limits descriptions", () => {
    expect(checkPlaylistDescription(" weekend ")).toBe("weekend");
    expect(() => checkPlaylistDescription("x".repeat(1001))).toThrow();
    expect(() => checkPlaylistDescription(null)).toThrow();
  });
});

describe("ids and positions", () => {
  it("accepts positive ids and non-negative positions", () => {
    expect(checkPlaylistId(3)).toBe(3);
    expect(() => checkPlaylistId(0)).toThrow();
    expect(() => checkPlaylistId(1.5)).toThrow();
    expect(checkPosition(0)).toBe(0);
    expect(() => checkPosition(-1)).toThrow();
  });
});

describe("describeItemCount", () => {
  it("counts videos", () => {
    expect(describeItemCount(0)).toBe("No videos");
    expect(describeItemCount(1)).toBe("1 video");
    expect(describeItemCount(12)).toBe("12 videos");
  });
});

describe("stepPosition", () => {
  it("moves within bounds", () => {
    expect(stepPosition(1, "up", 3)).toBe(0);
    expect(stepPosition(1, "down", 3)).toBe(2);
    expect(stepPosition(0, "up", 3)).toBeNull();
    expect(stepPosition(2, "down", 3)).toBeNull();
  });
});

describe("moveItem", () => {
  it("moves an item and shifts the rest", () => {
    expect(moveItem(["a", "b", "c", "d"], 0, 2)).toEqual(["b", "c", "a", "d"]);
    expect(moveItem(["a", "b", "c", "d"], 3, 0)).toEqual(["d", "a", "b", "c"]);
    expect(moveItem(["a", "b"], 0, 9)).toEqual(["b", "a"]);
    expect(moveItem(["a", "b"], 5, 0)).toEqual(["a", "b"]);
  });
});

describe("parsePlaylistId", () => {
  it("reads positive integer ids", () => {
    expect(parsePlaylistId("12")).toBe(12);
    expect(parsePlaylistId("0")).toBeNull();
    expect(parsePlaylistId("012")).toBeNull();
    expect(parsePlaylistId("1.5")).toBeNull();
    expect(parsePlaylistId("abc")).toBeNull();
    expect(parsePlaylistId("99999999999999999")).toBeNull();
  });
});
