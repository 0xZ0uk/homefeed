import { describe, expect, it } from "vitest";

import {
  formatAge,
  formatDuration,
  formatFeedDate,
  formatViews,
  isFeedDate,
} from "./format";

describe("formatDuration", () => {
  it("formats minutes and hours", () => {
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(65)).toBe("1:05");
    expect(formatDuration(600)).toBe("10:00");
    expect(formatDuration(3723)).toBe("1:02:03");
  });

  it("is null when unknown", () => {
    expect(formatDuration(null)).toBeNull();
    expect(formatDuration(undefined)).toBeNull();
    expect(formatDuration(-1)).toBeNull();
  });
});

describe("formatAge", () => {
  const now = new Date("2026-10-12T12:00:00Z");

  it("uses the largest whole unit", () => {
    expect(formatAge("2026-10-12T11:59:30Z", now)).toBe("just now");
    expect(formatAge("2026-10-12T11:59:00Z", now)).toBe("1 minute ago");
    expect(formatAge("2026-10-12T09:00:00Z", now)).toBe("3 hours ago");
    expect(formatAge("2026-10-11T12:00:00Z", now)).toBe("1 day ago");
    expect(formatAge("2026-09-28T12:00:00Z", now)).toBe("2 weeks ago");
    expect(formatAge("2025-10-01T12:00:00Z", now)).toBe("1 year ago");
  });

  it("treats future times as just now", () => {
    expect(formatAge("2026-10-12T13:00:00Z", now)).toBe("just now");
  });

  it("is null when unknown", () => {
    expect(formatAge(null, now)).toBeNull();
    expect(formatAge("not a date", now)).toBeNull();
  });
});

describe("formatViews", () => {
  it("compacts large counts", () => {
    expect(formatViews(1)).toBe("1 view");
    expect(formatViews(999)).toBe("999 views");
    expect(formatViews(1234)).toBe("1.2K views");
    expect(formatViews(2_500_000)).toBe("2.5M views");
  });

  it("is null when unknown", () => {
    expect(formatViews(null)).toBeNull();
  });
});

describe("formatFeedDate", () => {
  it("formats the calendar date without shifting time zones", () => {
    expect(formatFeedDate("2026-10-12")).toBe("Mon, Oct 12, 2026");
  });
});

describe("isFeedDate", () => {
  it("accepts real dates only", () => {
    expect(isFeedDate("2026-10-12")).toBe(true);
    expect(isFeedDate("2026-02-30")).toBe(false);
    expect(isFeedDate("2026-1-2")).toBe(false);
    expect(isFeedDate("today")).toBe(false);
    expect(isFeedDate(20261012)).toBe(false);
  });
});
