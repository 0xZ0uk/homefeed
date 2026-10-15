import { describe, expect, it } from "vitest";

import { DEEP_DIVE_DEPTH } from "./card";
import {
  CHANNEL_COLORS,
  FEED_FILTERS,
  channelColor,
  isFeedFilter,
  isFeedSort,
  matchesFilter,
  sortFeedItems,
  type FeedFilter,
  type FeedSort,
} from "./feed-grid";

describe("matchesFilter", () => {
  const matching = (
    filter: FeedFilter,
    item: Parameters<typeof matchesFilter>[0],
  ) => matchesFilter(item, filter);

  it("shows everything under all", () => {
    expect(matching("all", {})).toBe(true);
    expect(matching("all", { duration_seconds: null })).toBe(true);
    expect(matching("all", { channel_subscribed: true, llm: null })).toBe(true);
  });

  it("finds videos from channels I don't subscribe to", () => {
    expect(matching("new", { channel_subscribed: false })).toBe(true);
    expect(matching("new", { channel_subscribed: true })).toBe(false);
    // Unknown is not "new": a past feed or a tag page may not say.
    expect(matching("new", {})).toBe(false);
  });

  it("buckets by minutes", () => {
    expect(matching("quick", { duration_seconds: 599 })).toBe(true);
    expect(matching("quick", { duration_seconds: 600 })).toBe(false);
    expect(matching("medium", { duration_seconds: 600 })).toBe(true);
    expect(matching("medium", { duration_seconds: 1799 })).toBe(true);
    expect(matching("medium", { duration_seconds: 1800 })).toBe(false);
    expect(matching("medium", { duration_seconds: 599 })).toBe(false);
  });

  it("leaves videos of unknown length out of the length buckets", () => {
    for (const filter of ["quick", "medium", "deep"] as const) {
      expect(matching(filter, { duration_seconds: null })).toBe(false);
      expect(matching(filter, { duration_seconds: undefined })).toBe(false);
      expect(matching(filter, { duration_seconds: -1 })).toBe(false);
    }
  });

  it("calls a video a deep dive by its depth once it's tagged", () => {
    const depth = (value: number, seconds: number | null = 300) => ({
      duration_seconds: seconds,
      llm: { depth: value },
    });
    expect(matching("deep", depth(DEEP_DIVE_DEPTH))).toBe(true);
    expect(matching("deep", depth(0.95))).toBe(true);
    expect(matching("deep", depth(DEEP_DIVE_DEPTH - 0.01))).toBe(false);
    // The score decides, whatever the length: a long, shallow video isn't one.
    expect(matching("deep", depth(0.2, 5400))).toBe(false);
    expect(matching("deep", depth(0.9, null))).toBe(true);
  });

  it("calls a video that isn't tagged yet a deep dive when it's over 30 minutes", () => {
    expect(matching("deep", { duration_seconds: 1800, llm: null })).toBe(true);
    expect(matching("deep", { duration_seconds: 1799, llm: null })).toBe(false);
    expect(matching("deep", { duration_seconds: 7200 })).toBe(true);
  });

  it("has a filter for each chip", () => {
    expect(FEED_FILTERS.map(({ label }) => label)).toEqual([
      "All",
      "New to me",
      "Quick",
      "10–30 min",
      "Deep dives",
    ]);
  });
});

describe("isFeedFilter", () => {
  it("accepts known filters only", () => {
    expect(isFeedFilter("deep")).toBe(true);
    expect(isFeedFilter("long")).toBe(false);
    expect(isFeedFilter(undefined)).toBe(false);
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
