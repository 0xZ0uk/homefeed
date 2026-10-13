import { describe, expect, it } from "vitest";

import {
  describeFilters,
  describeLastRun,
  filtersOf,
  parseSearchParams,
  searchParamsFor,
} from "./search";

describe("parseSearchParams", () => {
  it("keeps known values and collapses whitespace in the query", () => {
    expect(
      parseSearchParams({
        q: "  hand   planes ",
        sort: "upload_date",
        upload_date: "week",
        duration: "long",
      }),
    ).toEqual({
      q: "hand planes",
      sort: "upload_date",
      upload_date: "week",
      duration: "long",
    });
  });

  it("drops unknown values, defaults and blank queries", () => {
    expect(
      parseSearchParams({
        q: "   ",
        sort: "relevance",
        upload_date: "decade",
        duration: 3,
        extra: "x",
      }),
    ).toEqual({});
  });

  it("accepts numeric queries and caps the length", () => {
    expect(parseSearchParams({ q: 1984 })).toEqual({ q: "1984" });
    expect(parseSearchParams({ q: "x".repeat(300) }).q).toHaveLength(200);
  });
});

describe("filtersOf", () => {
  it("fills in the defaults", () => {
    expect(filtersOf({ q: "wood" })).toEqual({
      sort: "relevance",
      upload_date: null,
      duration: null,
    });
    expect(filtersOf({ sort: "rating", duration: "short" })).toEqual({
      sort: "rating",
      upload_date: null,
      duration: "short",
    });
  });
});

describe("searchParamsFor", () => {
  it("turns a saved search into search page params", () => {
    expect(
      searchParamsFor("wood", {
        sort: "relevance",
        upload_date: "month",
        duration: null,
      }),
    ).toEqual({ q: "wood", upload_date: "month" });
  });
});

describe("describeFilters", () => {
  it("lists the non-default filters", () => {
    expect(
      describeFilters({
        sort: "upload_date",
        upload_date: "week",
        duration: "long",
      }),
    ).toBe("Newest first · This week · Over 20 minutes");
    expect(describeFilters({ sort: "relevance", duration: "medium" })).toBe(
      "4–20 minutes",
    );
  });

  it("is null for a plain search", () => {
    expect(
      describeFilters({ sort: "relevance", upload_date: null, duration: null }),
    ).toBeNull();
    expect(describeFilters({})).toBeNull();
  });
});

describe("describeLastRun", () => {
  const now = new Date("2026-10-12T09:00:00Z");
  const base = {
    schedule: "daily" as const,
    last_run_at: "2026-10-12T06:00:00.000Z",
    last_found_count: 10,
    last_error: null,
  };

  it("reports the count", () => {
    expect(describeLastRun(base, now)).toBe("Last run 3 hours ago: 10 videos.");
    expect(describeLastRun({ ...base, last_found_count: 1 }, now)).toBe(
      "Last run 3 hours ago: 1 video.",
    );
  });

  it("reports failures", () => {
    expect(
      describeLastRun({ ...base, last_error: "HTTP Error 429" }, now),
    ).toBe("Last run 3 hours ago failed: HTTP Error 429");
  });

  it("explains searches that never ran", () => {
    const never = { ...base, last_run_at: null, last_found_count: null };
    expect(describeLastRun(never, now)).toBe(
      "Runs with the next daily feed build.",
    );
    expect(describeLastRun({ ...never, schedule: "paused" }, now)).toBe(
      "Paused before its first run.",
    );
  });
});
