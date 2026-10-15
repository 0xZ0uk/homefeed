import { describe, expect, it } from "vitest";

import {
  formatClock,
  formatFeedDay,
  leftovers,
  leftoversHeading,
  minutesIntoDay,
  nextFeedText,
  previousFeedOf,
  queueSummary,
} from "./today";

describe("formatClock", () => {
  it("drops the leading zero of the hour", () => {
    expect(formatClock("06:00")).toBe("6:00");
    expect(formatClock("00:05")).toBe("0:05");
    expect(formatClock("14:30")).toBe("14:30");
    expect(formatClock("6:00")).toBe("6:00");
  });

  it("leaves what isn't a time as it is", () => {
    expect(formatClock("soon")).toBe("soon");
  });
});

describe("minutesIntoDay", () => {
  const now = new Date("2026-10-15T01:30:00Z");

  it("reads the time of day in the time zone", () => {
    expect(minutesIntoDay(now, "UTC")).toBe(90);
    expect(minutesIntoDay(now, "Asia/Tokyo")).toBe(10 * 60 + 30);
    expect(minutesIntoDay(now, "America/Los_Angeles")).toBe(18 * 60 + 30);
  });

  it("goes by the browser's time zone for one it doesn't know", () => {
    expect(minutesIntoDay(now, "Mars/Phobos")).toBe(minutesIntoDay(now, null));
  });

  it("starts the day at 0, not 24", () => {
    expect(minutesIntoDay(new Date("2026-10-15T00:05:00Z"), "UTC")).toBe(5);
  });
});

describe("nextFeedText", () => {
  const night = new Date("2026-10-15T01:30:00Z");

  it("names the time when the feed is still to come today", () => {
    expect(nextFeedText("06:00", night, "UTC")).toBe("Next feed at 6:00");
    expect(nextFeedText("06:00", new Date("2026-10-15T05:59:00Z"), "UTC")).toBe(
      "Next feed at 6:00",
    );
  });

  it("says tomorrow once today's time has passed", () => {
    expect(nextFeedText("06:00", new Date("2026-10-15T06:00:00Z"), "UTC")).toBe(
      "Next feed tomorrow at 6:00",
    );
    expect(nextFeedText("06:00", night, "Asia/Tokyo")).toBe(
      "Next feed tomorrow at 6:00",
    );
  });

  it("goes by the time zone the feed is built in", () => {
    // 01:30 UTC is 18:30 the day before in Los Angeles, and 03:30 in Cairo.
    expect(nextFeedText("19:00", night, "America/Los_Angeles")).toBe(
      "Next feed at 19:00",
    );
    expect(nextFeedText("03:00", night, "Africa/Cairo")).toBe(
      "Next feed tomorrow at 3:00",
    );
  });

  it("copes with a time it can't read", () => {
    expect(nextFeedText("whenever", night, "UTC")).toBe(
      "Next feed at whenever",
    );
  });
});

describe("formatFeedDay", () => {
  it("is the weekday, month and day", () => {
    expect(formatFeedDay("2026-10-14")).toBe("Wed, Oct 14");
    expect(formatFeedDay("2026-01-01")).toBe("Thu, Jan 1");
  });

  it("leaves what isn't a date as it is", () => {
    expect(formatFeedDay("yesterday")).toBe("yesterday");
  });
});

describe("leftovers", () => {
  const item = (id: number, watched: boolean, dismissed_at: string | null) => ({
    id,
    watched,
    dismissed_at,
  });

  it("keeps the picks that are neither watched nor dismissed, in order", () => {
    const items = [
      item(1, false, null),
      item(2, true, null),
      item(3, false, "2026-10-14T10:00:00Z"),
      item(4, false, null),
    ];

    expect(leftovers(items).map((i) => i.id)).toEqual([1, 4]);
  });

  it("has none when everything was seen", () => {
    expect(leftovers([item(1, true, null)])).toEqual([]);
    expect(leftovers([])).toEqual([]);
  });

  it("heads them with the day", () => {
    expect(leftoversHeading("2026-10-14")).toBe(
      "Still unwatched from Wed, Oct 14",
    );
  });
});

describe("previousFeedOf", () => {
  it("is the newest feed that picked anything", () => {
    const feeds = [
      { date: "2026-10-14", item_count: 0 },
      { date: "2026-10-13", item_count: 20 },
      { date: "2026-10-12", item_count: 15 },
    ];

    expect(previousFeedOf(feeds)?.date).toBe("2026-10-13");
  });

  it("is none when no feed picked anything", () => {
    expect(previousFeedOf([])).toBeNull();
    expect(previousFeedOf([{ date: "2026-10-14", item_count: 0 }])).toBeNull();
  });
});

describe("queueSummary", () => {
  it("counts the queued videos", () => {
    expect(queueSummary(0)).toBe("Nothing in your queue");
    expect(queueSummary(1)).toBe("1 video in your queue");
    expect(queueSummary(3)).toBe("3 videos in your queue");
  });
});
