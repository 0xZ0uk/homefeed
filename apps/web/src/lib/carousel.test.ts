import { describe, expect, it } from "vitest";

import { clampPage, nextPage, pageCount, sourceLabel } from "./carousel";

describe("pageCount", () => {
  it("rounds a partial page up", () => {
    expect(pageCount(10, 2)).toBe(5);
    expect(pageCount(9, 2)).toBe(5);
    expect(pageCount(10, 1)).toBe(10);
  });

  it("is at least one", () => {
    expect(pageCount(0, 2)).toBe(1);
    expect(pageCount(3, 0)).toBe(3);
  });
});

describe("nextPage", () => {
  it("wraps after the last page", () => {
    expect(nextPage(0, 5)).toBe(1);
    expect(nextPage(4, 5)).toBe(0);
    expect(nextPage(0, 1)).toBe(0);
    expect(nextPage(3, 0)).toBe(0);
  });
});

describe("clampPage", () => {
  it("keeps the page in range", () => {
    expect(clampPage(-1, 5)).toBe(0);
    expect(clampPage(7, 5)).toBe(4);
    expect(clampPage(2, 5)).toBe(2);
    expect(clampPage(2, 0)).toBe(0);
  });
});

describe("sourceLabel", () => {
  it("names the sources outside subscriptions", () => {
    expect(sourceLabel("related")).toBe("Related");
    expect(sourceLabel("channel_graph")).toBe("Featured channel");
    expect(sourceLabel("subscription")).toBeNull();
  });

  it("names the tag, search or external source when it can", () => {
    expect(sourceLabel("tag", "woodworking")).toBe("#woodworking");
    expect(sourceLabel("saved_search", "hand planes")).toBe("hand planes");
    expect(sourceLabel("external", "r/woodworking")).toBe("r/woodworking");
    expect(sourceLabel("saved_search", "a".repeat(40))).toBe(
      `${"a".repeat(27)}…`,
    );
    // The seed video's id of a related video says nothing.
    expect(sourceLabel("related", "w0000000000")).toBe("Related");
    expect(sourceLabel("tag", "  ")).toBe("Tag");
  });
});
