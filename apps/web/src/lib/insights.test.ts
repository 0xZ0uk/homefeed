import type { WeekInsightsOut } from "@homefeed/api-client";
import { describe, expect, it } from "vitest";

import {
  formatPercent,
  formatWeek,
  isGoodBucket,
  labelStride,
  overallGoodRate,
  overallRatingRate,
  plural,
  totalScoreCounts,
  trendPath,
  trendPoints,
  type ChartBox,
} from "./insights";

function week(
  weekStart: string,
  overrides: Partial<WeekInsightsOut> = {},
): WeekInsightsOut {
  return {
    week_start: weekStart,
    rated_count: 0,
    good_count: 0,
    good_rate: null,
    score_counts: [10, 9, 8, 7, 6, 5, 4, 3, 2, 1].map((score) => ({
      score,
      count: 0,
    })),
    shown_count: 0,
    shown_rated_count: 0,
    rating_rate: null,
    feed_count: 0,
    model_feed_count: 0,
    score_share: null,
    ...overrides,
  };
}

const BOX: ChartBox = {
  width: 120,
  height: 110,
  left: 10,
  right: 10,
  top: 5,
  bottom: 5,
};

describe("formatting", () => {
  it("rounds rates to whole percentages and marks unknown ones", () => {
    expect(formatPercent(0.625)).toBe("63%");
    expect(formatPercent(1)).toBe("100%");
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(null)).toBe("–");
    expect(formatPercent(undefined)).toBe("–");
  });

  it("names weeks by their Monday", () => {
    expect(formatWeek("2026-10-05")).toBe("Oct 5");
    expect(formatWeek("nope")).toBe("nope");
  });

  it("pluralizes counts", () => {
    expect(plural(1, "rating")).toBe("1 rating");
    expect(plural(0, "rating")).toBe("0 ratings");
  });
});

describe("totals", () => {
  const weeks = [
    week("2026-09-28", {
      rated_count: 4,
      good_count: 1,
      shown_count: 10,
      shown_rated_count: 2,
      score_counts: [
        { score: 10, count: 1 },
        { score: 1, count: 3 },
      ],
    }),
    week("2026-10-05", {
      rated_count: 2,
      good_count: 2,
      shown_count: 5,
      shown_rated_count: 4,
      score_counts: [
        { score: 10, count: 2 },
        { score: 1, count: 0 },
      ],
    }),
  ];

  it("weights rates by counts rather than averaging weeks", () => {
    expect(overallGoodRate(weeks)).toBe(0.5);
    expect(overallRatingRate(weeks)).toBe(0.4);
  });

  it("has no rates without data", () => {
    expect(overallGoodRate([week("2026-10-05")])).toBeNull();
    expect(overallRatingRate([])).toBeNull();
  });

  it("sums scores across weeks, keeping their order", () => {
    expect(totalScoreCounts(weeks)).toEqual([
      { score: 10, count: 3 },
      { score: 1, count: 3 },
    ]);
  });
});

describe("score buckets", () => {
  it("counts a bucket as good when all of it reaches the threshold", () => {
    expect(isGoodBucket(6, 5.5)).toBe(true);
    expect(isGoodBucket(5, 5.5)).toBe(false);
    expect(isGoodBucket(10, 5.5)).toBe(true);
  });
});

describe("trend chart", () => {
  it("thins x-axis labels so they stay apart", () => {
    expect(labelStride(12, 1100, 64)).toBe(1);
    expect(labelStride(12, 580, 64)).toBe(2);
    expect(labelStride(12, 280, 64)).toBe(3);
    expect(labelStride(1, 280, 64)).toBe(1);
  });

  it("spreads weeks across the plot and maps rates bottom to top", () => {
    const points = trendPoints(
      [
        week("2026-09-28", { good_rate: 0 }),
        week("2026-10-05", { good_rate: 0.5 }),
        week("2026-10-12", { good_rate: 1 }),
      ],
      BOX,
    );

    expect(points.map(({ x, y }) => [x, y])).toEqual([
      [10, 105],
      [60, 55],
      [110, 5],
    ]);
  });

  it("centers a single week", () => {
    const points = trendPoints([week("2026-10-12")], BOX);

    expect(points.map(({ x, y }) => [x, y])).toEqual([[60, null]]);
  });

  it("breaks the line at weeks without ratings", () => {
    const points = trendPoints(
      [
        week("2026-09-21", { good_rate: 1 }),
        week("2026-09-28", { good_rate: 0.5 }),
        week("2026-10-05"),
        week("2026-10-12", { good_rate: 0 }),
      ],
      BOX,
    );

    expect(trendPath(points)).toBe("M10 5 L43.3 55 M110 105");
  });
});
