import { describe, expect, it } from "vitest";

import { channelCount, channelHits } from "./onboarding";

const result = (channel: string, title: string, handle?: string | null) => ({
  channel_id: `UC${channel.repeat(22)}`,
  channel_title: `Channel ${channel}`,
  channel_handle: handle,
  title,
});

describe("channelHits", () => {
  it("lists each channel once, in order of first appearance", () => {
    const hits = channelHits([
      result("a", "First", "@a"),
      result("b", "Second"),
      result("a", "Third", "@a"),
    ]);
    expect(hits).toEqual([
      {
        channel_id: `UC${"a".repeat(22)}`,
        title: "Channel a",
        handle: "@a",
        sample_video: "First",
      },
      {
        channel_id: `UC${"b".repeat(22)}`,
        title: "Channel b",
        handle: null,
        sample_video: "Second",
      },
    ]);
  });

  it("stops at the limit", () => {
    const results = ["a", "b", "c", "d"].map((c) => result(c, c));
    expect(channelHits(results, 2).map((h) => h.title)).toEqual([
      "Channel a",
      "Channel b",
    ]);
  });

  it("is empty without results", () => {
    expect(channelHits([])).toEqual([]);
  });
});

describe("channelCount", () => {
  it("pluralizes", () => {
    expect(channelCount(1)).toBe("1 channel");
    expect(channelCount(0)).toBe("0 channels");
    expect(channelCount(7)).toBe("7 channels");
  });
});
