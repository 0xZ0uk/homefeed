import { describe, expect, it } from "vitest";

import {
  TAG_PAGE_SIZE,
  describeVideoCount,
  isTagSlug,
  pageCount,
  parseTagParams,
  tagWindow,
} from "./tags";

describe("parseTagParams", () => {
  it("keeps later pages", () => {
    expect(parseTagParams({ page: 3 })).toEqual({ page: 3 });
    expect(parseTagParams({ page: "2" })).toEqual({ page: 2 });
  });

  it("drops the first page, bad pages and unknown keys", () => {
    expect(parseTagParams({ page: 1, sort: "x" })).toEqual({});
    expect(parseTagParams({ page: 0 })).toEqual({});
    expect(parseTagParams({ page: 2.5 })).toEqual({});
    expect(parseTagParams({ page: "abc" })).toEqual({});
  });
});

describe("tagWindow", () => {
  it("offsets by whole pages", () => {
    expect(tagWindow({})).toEqual({ limit: TAG_PAGE_SIZE, offset: 0 });
    expect(tagWindow({ page: 3 })).toEqual({
      limit: TAG_PAGE_SIZE,
      offset: 2 * TAG_PAGE_SIZE,
    });
  });
});

describe("pageCount", () => {
  it("is at least one and rounds up", () => {
    expect(pageCount(0)).toBe(1);
    expect(pageCount(TAG_PAGE_SIZE)).toBe(1);
    expect(pageCount(TAG_PAGE_SIZE + 1)).toBe(2);
  });
});

describe("isTagSlug", () => {
  it("accepts non-empty slugs up to the limit", () => {
    expect(isTagSlug("rust")).toBe(true);
    expect(isTagSlug("")).toBe(false);
    expect(isTagSlug("a".repeat(101))).toBe(false);
  });
});

describe("describeVideoCount", () => {
  it("pluralises", () => {
    expect(describeVideoCount(0)).toBe("0 videos");
    expect(describeVideoCount(1)).toBe("1 video");
    expect(describeVideoCount(2)).toBe("2 videos");
  });
});
