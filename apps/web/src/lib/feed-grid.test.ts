import { describe, expect, it } from "vitest";

import {
  CHANNEL_COLORS,
  channelColor,
  isLengthFilter,
  matchesLength,
} from "./feed-grid";

describe("matchesLength", () => {
  it("buckets by minutes", () => {
    expect(matchesLength(599, "short")).toBe(true);
    expect(matchesLength(600, "short")).toBe(false);
    expect(matchesLength(600, "medium")).toBe(true);
    expect(matchesLength(1799, "medium")).toBe(true);
    expect(matchesLength(1800, "long")).toBe(true);
    expect(matchesLength(1800, "medium")).toBe(false);
  });

  it("shows unknown lengths only under all", () => {
    expect(matchesLength(null, "all")).toBe(true);
    expect(matchesLength(null, "short")).toBe(false);
    expect(matchesLength(undefined, "long")).toBe(false);
  });
});

describe("isLengthFilter", () => {
  it("accepts known filters only", () => {
    expect(isLengthFilter("long")).toBe(true);
    expect(isLengthFilter("huge")).toBe(false);
    expect(isLengthFilter(undefined)).toBe(false);
  });
});

describe("channelColor", () => {
  it("is stable per channel and from the palette", () => {
    const color = channelColor("UCwwwwwwwwwwwwwwwwwwwwww");
    expect(channelColor("UCwwwwwwwwwwwwwwwwwwwwww")).toBe(color);
    expect(CHANNEL_COLORS).toContain(color);
  });
});
