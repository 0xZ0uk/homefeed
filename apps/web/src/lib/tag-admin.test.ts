import { describe, expect, it } from "vitest";

import { mergeSummary, videoCount } from "./tag-admin";

describe("videoCount", () => {
  it("pluralizes", () => {
    expect(videoCount(0)).toBe("0 videos");
    expect(videoCount(1)).toBe("1 video");
    expect(videoCount(12)).toBe("12 videos");
  });
});

describe("mergeSummary", () => {
  it("names both tags", () => {
    expect(mergeSummary("node", "javascript")).toContain("“node”");
    expect(mergeSummary("node", "javascript")).toContain("“javascript”");
  });
});
