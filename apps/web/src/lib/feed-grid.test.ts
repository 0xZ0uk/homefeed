import { describe, expect, it } from "vitest";

import {
  CHANNEL_COLORS,
  channelColor,
  isFeedSort,
  isLengthFilter,
  matchesLength,
  sortFeedItems,
  type FeedSort,
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

describe("sortFeedItems", () => {
  const item = (
    id: string,
    published_at: string | null,
    view_count: number | null,
    duration_seconds: number | null,
    channel: number,
  ) => ({
    id,
    published_at,
    view_count,
    duration_seconds,
    breakdown: { channel },
  });
  const items = [
    item("a", "2026-10-02T00:00:00Z", 500, 300, 0.2),
    item("b", "2026-10-05T00:00:00Z", null, 1200, 0.8),
    item("c", null, 9000, null, 0.2),
    item("d", "2026-10-01T00:00:00Z", 40, 60, -0.5),
  ];
  const ids = (sort: FeedSort) => sortFeedItems(items, sort).map((i) => i.id);

  it("keeps the feed's order when ranked", () => {
    expect(ids("ranked")).toEqual(["a", "b", "c", "d"]);
  });

  it("sorts by upload date, unknown dates last", () => {
    expect(ids("recent")).toEqual(["b", "a", "d", "c"]);
    expect(ids("oldest")).toEqual(["d", "a", "b", "c"]);
  });

  it("sorts by views, unknown views last", () => {
    expect(ids("most-viewed")).toEqual(["c", "a", "d", "b"]);
    expect(ids("least-viewed")).toEqual(["d", "a", "c", "b"]);
  });

  it("sorts by length, unknown lengths last", () => {
    expect(ids("shortest")).toEqual(["d", "a", "b", "c"]);
    expect(ids("longest")).toEqual(["b", "a", "d", "c"]);
  });

  it("sorts by channel score, keeping feed order for ties", () => {
    expect(ids("channel-score")).toEqual(["b", "a", "c", "d"]);
  });

  it("doesn't change the items it's given", () => {
    sortFeedItems(items, "recent");
    expect(items.map((i) => i.id)).toEqual(["a", "b", "c", "d"]);
  });
});

describe("isFeedSort", () => {
  it("accepts known sorts only", () => {
    expect(isFeedSort("most-viewed")).toBe(true);
    expect(isFeedSort("random")).toBe(false);
  });
});
