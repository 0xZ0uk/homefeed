import { describe, expect, it } from "vitest";

import {
  formatKind,
  formatMetric,
  formatTimestamp,
  holdoutSize,
} from "./models";

describe("formatMetric", () => {
  it("rounds to 3 decimals", () => {
    expect(formatMetric(0.12345)).toBe("0.123");
    expect(formatMetric(-0.5)).toBe("-0.500");
    expect(formatMetric(0)).toBe("0.000");
  });

  it("is a dash when undefined", () => {
    expect(formatMetric(null)).toBe("–");
    expect(formatMetric(undefined)).toBe("–");
    expect(formatMetric(Number.NaN)).toBe("–");
  });
});

describe("formatTimestamp", () => {
  it("formats in UTC", () => {
    expect(formatTimestamp("2026-10-01T03:05:00.000Z")).toBe(
      "Oct 1, 2026, 03:05 UTC",
    );
  });

  it("is a dash when unset and the raw text when unparseable", () => {
    expect(formatTimestamp(null)).toBe("–");
    expect(formatTimestamp("")).toBe("–");
    expect(formatTimestamp("not a date")).toBe("not a date");
  });
});

describe("formatKind", () => {
  it("labels known kinds and passes others through", () => {
    expect(formatKind("lightgbm")).toBe("LightGBM");
    expect(formatKind("ridge")).toBe("Ridge");
    expect(formatKind("other")).toBe("other");
  });
});

describe("holdoutSize", () => {
  it("reads n_holdout from the training report", () => {
    expect(holdoutSize({ n_holdout: 12 })).toBe(12);
    expect(holdoutSize({})).toBeNull();
    expect(holdoutSize({ n_holdout: "12" })).toBeNull();
  });
});
