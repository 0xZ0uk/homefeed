import { describe, expect, it } from "vitest";

import {
  HISTORY_PAGE_SIZE,
  describeProgress,
  pageWindow,
  parseHistoryParams,
  progressFraction,
} from "./history";

describe("parseHistoryParams", () => {
  it("keeps the query (whitespace collapsed) and later pages", () => {
    expect(parseHistoryParams({ q: "  hand   planes ", page: 3 })).toEqual({
      q: "hand planes",
      page: 3,
    });
    expect(parseHistoryParams({ q: 42, page: "2" })).toEqual({
      q: "42",
      page: 2,
    });
  });

  it("drops blanks, the first page, bad pages and unknown keys", () => {
    expect(parseHistoryParams({ q: "   ", page: 1, sort: "x" })).toEqual({});
    expect(parseHistoryParams({ page: 0 })).toEqual({});
    expect(parseHistoryParams({ page: 2.5 })).toEqual({});
    expect(parseHistoryParams({ page: "abc" })).toEqual({});
    expect(parseHistoryParams({ q: ["a"] })).toEqual({});
  });

  it("caps the query length", () => {
    expect(parseHistoryParams({ q: "x".repeat(300) }).q).toHaveLength(200);
  });
});

describe("pageWindow", () => {
  it("asks for one more than a page, from the page's start", () => {
    expect(pageWindow({})).toEqual({ limit: HISTORY_PAGE_SIZE + 1, offset: 0 });
    expect(pageWindow({ page: 3 })).toEqual({
      limit: HISTORY_PAGE_SIZE + 1,
      offset: 2 * HISTORY_PAGE_SIZE,
    });
  });
});

describe("describeProgress", () => {
  it("says where I stopped", () => {
    expect(
      describeProgress({
        position: 754,
        resume_position: 754,
        duration: 2400,
        finished: false,
      }),
    ).toBe("Stopped at 12:34 of 40:00");
    expect(
      describeProgress({ position: 65, resume_position: 65, finished: true }),
    ).toBe("Stopped at 1:05");
  });

  it("says finished, or nothing", () => {
    expect(
      describeProgress({
        position: 600,
        resume_position: null,
        finished: true,
      }),
    ).toBe("Finished");
    expect(describeProgress({ position: 2, finished: false })).toBeNull();
  });
});

describe("progressFraction", () => {
  it("is the share watched when it can be resumed", () => {
    expect(
      progressFraction({
        position: 150,
        resume_position: 150,
        duration: 600,
        finished: false,
      }),
    ).toBe(0.25);
    expect(
      progressFraction({
        position: 150,
        resume_position: 150,
        finished: false,
      }),
    ).toBeNull();
    expect(
      progressFraction({ position: 600, duration: 600, finished: true }),
    ).toBeNull();
  });
});
