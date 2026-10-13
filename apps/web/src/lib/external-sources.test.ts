import { describe, expect, it } from "vitest";

import {
  isSourceKind,
  isSourceSchedule,
  sourceStatus,
} from "./external-sources";

const now = new Date("2026-10-12T12:00:00Z");
const fresh = {
  last_fetched_at: null,
  last_success_at: null,
  consecutive_failures: 0,
  last_error: null,
  last_found_count: null,
};

describe("sourceStatus", () => {
  it("says when a source hasn't been checked", () => {
    expect(sourceStatus(fresh, now)).toBe("Not checked yet");
  });

  it("shows the last check and what it found", () => {
    const checked = {
      ...fresh,
      last_fetched_at: "2026-10-12T10:00:00Z",
      last_success_at: "2026-10-12T10:00:00Z",
      last_found_count: 4,
    };
    expect(sourceStatus(checked, now)).toBe("Checked 2 hours ago · 4 videos");
    expect(sourceStatus({ ...checked, last_found_count: 1 }, now)).toBe(
      "Checked 2 hours ago · 1 video",
    );
  });

  it("shows failures with the last error", () => {
    expect(
      sourceStatus(
        {
          ...fresh,
          consecutive_failures: 1,
          last_error: "HTTP Error 404 fetching https://example.com/feed",
        },
        now,
      ),
    ).toBe("Failing (once): HTTP Error 404 fetching https://example.com/feed");
    expect(sourceStatus({ ...fresh, consecutive_failures: 3 }, now)).toBe(
      "Failing (3 times)",
    );
  });
});

describe("guards", () => {
  it("accept only known kinds and schedules", () => {
    expect(isSourceKind("rss")).toBe(true);
    expect(isSourceKind("twitter")).toBe(false);
    expect(isSourceSchedule("weekly")).toBe(true);
    expect(isSourceSchedule("monthly")).toBe(false);
  });
});
