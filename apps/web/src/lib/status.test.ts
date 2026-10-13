import { describe, expect, it } from "vitest";

import {
  DEFAULT_STATUS_HOURS,
  formatAgo,
  formatMilliseconds,
  healthBadgeClass,
  healthLabel,
  healthSummary,
  operationLabel,
  parseStatusHours,
} from "./status";

const NOW = new Date("2026-10-13T12:00:00Z");

describe("parseStatusHours", () => {
  it("accepts the offered windows, as numbers or strings", () => {
    expect(parseStatusHours(24)).toBe(24);
    expect(parseStatusHours(168)).toBe(168);
    expect(parseStatusHours("168")).toBe(168);
  });

  it("falls back to the default otherwise", () => {
    expect(parseStatusHours(undefined)).toBe(DEFAULT_STATUS_HOURS);
    expect(parseStatusHours(5)).toBe(DEFAULT_STATUS_HOURS);
    expect(parseStatusHours("abc")).toBe(DEFAULT_STATUS_HOURS);
  });
});

describe("health", () => {
  it("has a label, badge and summary for every state", () => {
    for (const health of ["ok", "degraded", "failing", "unknown"] as const) {
      expect(healthLabel(health)).toBeTruthy();
      expect(healthBadgeClass(health)).toMatch(/^bg-/);
      expect(healthSummary(health)).toMatch(/\.$/);
    }
    expect(healthLabel("failing")).toBe("Failing");
  });
});

describe("operationLabel", () => {
  it("names known operations and passes others through", () => {
    expect(operationLabel("get_video")).toBe("Video metadata");
    expect(operationLabel("get_channel_feed")).toBe("Channel RSS feeds");
    expect(operationLabel("something_new")).toBe("something_new");
  });
});

describe("formatAgo", () => {
  it("rounds down to minutes, hours or days", () => {
    expect(formatAgo("2026-10-13T11:59:30Z", NOW)).toBe("just now");
    expect(formatAgo("2026-10-13T11:55:00Z", NOW)).toBe("5 min ago");
    expect(formatAgo("2026-10-13T09:00:00Z", NOW)).toBe("3 h ago");
    expect(formatAgo("2026-10-12T00:00:00Z", NOW)).toBe("36 h ago");
    expect(formatAgo("2026-10-10T12:00:00Z", NOW)).toBe("3 d ago");
  });

  it("is a dash when unset and the input when unparsable", () => {
    expect(formatAgo(null, NOW)).toBe("–");
    expect(formatAgo("nope", NOW)).toBe("nope");
  });
});

describe("formatMilliseconds", () => {
  it("uses ms below a second and seconds above", () => {
    expect(formatMilliseconds(850)).toBe("850 ms");
    expect(formatMilliseconds(1234)).toBe("1.2 s");
    expect(formatMilliseconds(null)).toBe("–");
  });
});
