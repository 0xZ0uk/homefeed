import type { WeekInsightsOut } from "@homefeed/api-client";
import { describe, expect, it } from "vitest";

import {
  averageGoodRate,
  deltaPoints,
  DEFAULT_WEEK_RANGE,
  formatDay,
  formatPercent,
  formatWeek,
  goodRateDelta,
  insightsSummary,
  isGoodBucket,
  labelStride,
  lastN,
  modelShareDelta,
  overallGoodRate,
  overallModelShare,
  overallRatingRate,
  parseWeekRange,
  plural,
  ratingRateDelta,
  totalScoreCounts,
  trendPath,
  trendPoints,
  weeklyInsightsCsv,
  WEEK_RANGES,
  type ChartBox,
  type WeekRange,
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

  it("names days the same way", () => {
    expect(formatDay("2026-10-15")).toBe("Oct 15");
    expect(formatDay("nope")).toBe("nope");
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
  it("counts a score as good when it reaches the threshold", () => {
    expect(isGoodBucket(6, 6)).toBe(true);
    expect(isGoodBucket(5, 6)).toBe(false);
    expect(isGoodBucket(10, 6)).toBe(true);
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

describe("week ranges", () => {
  it("accepts the supported spans as numbers", () => {
    for (const weeks of WEEK_RANGES satisfies readonly WeekRange[]) {
      expect(parseWeekRange(weeks)).toBe(weeks);
    }
  });

  it("accepts numeric strings", () => {
    expect(parseWeekRange("4")).toBe(4);
    expect(parseWeekRange("26")).toBe(26);
    expect(parseWeekRange(" 12 ")).toBe(12);
  });

  it("falls back to the default for anything else", () => {
    for (const value of [
      0,
      3,
      15,
      104,
      "13",
      "1e1",
      "",
      "nope",
      null,
      undefined,
      NaN,
    ]) {
      expect(parseWeekRange(value)).toBe(DEFAULT_WEEK_RANGE);
    }
    expect(DEFAULT_WEEK_RANGE).toBe(12);
  });
});

describe("lastN and points", () => {
  const items = [1, 2, 3, 4, 5];

  it("takes the tail", () => {
    expect(lastN(items, 2)).toEqual([4, 5]);
    expect(lastN(items, 99)).toEqual(items);
    expect(lastN(items, 0)).toEqual([]);
    expect(lastN(items, -1)).toEqual([]);
  });

  it("differences rates in whole percentage points", () => {
    expect(deltaPoints(0.75, 0.25)).toBe(50);
    expect(deltaPoints(0.4, 0.55)).toBe(-15);
    expect(deltaPoints(0.666, 0.5)).toBe(17);
    expect(deltaPoints(0.5, 0.5)).toBe(0);
    expect(deltaPoints(null, 0.5)).toBeNull();
    expect(deltaPoints(0.5, undefined)).toBeNull();
    expect(deltaPoints(NaN, 0.5)).toBeNull();
  });
});

describe("window deltas", () => {
  // Four weeks with a low rate, then four with a high one.
  const weeks = [
    ...[0, 1, 2, 3].map((n) =>
      week(`2026-08-${3 + n}`, { rated_count: 4, good_count: 1 }),
    ),
    ...[0, 1, 2, 3].map((n) =>
      week(`2026-09-${7 + n}`, { rated_count: 4, good_count: 3 }),
    ),
  ];

  it("pools each window before comparing, so counts weight the delta", () => {
    expect(overallGoodRate(weeks.slice(0, 4))).toBe(0.25);
    expect(overallGoodRate(weeks.slice(4))).toBe(0.75);
    expect(goodRateDelta(weeks)).toBe(50);
  });

  it("is null when either window has no ratings", () => {
    expect(goodRateDelta([week("2026-10-05"), week("2026-10-12")])).toBeNull();
    // All the ratings sit in the last window, so the earlier one is empty.
    const oneSided = [
      ...[0, 1, 2, 3].map(() => week("2026-09-07")),
      week("2026-10-05", { rated_count: 2, good_count: 1 }),
      week("2026-10-12", { rated_count: 2, good_count: 1 }),
    ];
    expect(goodRateDelta(oneSided)).toBeNull();
  });

  it("honors a custom window", () => {
    const sixWeeks = [
      ...[0, 1, 2].map((n) =>
        week(`2026-08-${3 + n}`, { rated_count: 4, good_count: 1 }),
      ),
      week("2026-09-07", { rated_count: 4, good_count: 1 }),
      week("2026-09-14", { rated_count: 4, good_count: 3 }),
      week("2026-09-21", { rated_count: 4, good_count: 3 }),
      week("2026-09-28", { rated_count: 4, good_count: 3 }),
    ];
    // The previous window (one low week, one high week) pools to 50%.
    expect(goodRateDelta(sixWeeks, 2)).toBe(25);
  });

  it("compares rating rates the same way", () => {
    const rated = [
      ...[0, 1, 2, 3].map((n) =>
        week(`2026-08-${3 + n}`, { shown_count: 10, shown_rated_count: 2 }),
      ),
      ...[0, 1, 2, 3].map((n) =>
        week(`2026-09-${7 + n}`, { shown_count: 10, shown_rated_count: 6 }),
      ),
    ];
    expect(ratingRateDelta(rated)).toBe(40);
    expect(
      ratingRateDelta([week("2026-10-05", { shown_count: 10 })]),
    ).toBeNull();
  });

  it("averages model shares, skipping weeks without a share", () => {
    const shares = (model: number) => ({
      model,
      curation: 0.1,
      similarity: 0.1,
    });
    const shared = [
      week("2026-08-03", { score_share: shares(0.4) }),
      week("2026-08-10"),
      week("2026-08-17", { score_share: shares(0.2) }),
      week("2026-08-24"),
      week("2026-08-31", { score_share: shares(0.8) }),
      week("2026-09-07"),
      week("2026-09-14", { score_share: shares(0.4) }),
      week("2026-09-21"),
    ];
    expect(overallModelShare(shared.slice(0, 4))).toBeCloseTo(0.3);
    expect(overallModelShare(shared.slice(4))).toBeCloseTo(0.6);
    expect(modelShareDelta(shared)).toBe(30);
    expect(
      modelShareDelta([week("2026-10-05"), week("2026-10-12")]),
    ).toBeNull();
  });
});

describe("summary", () => {
  it("pools the good rate over all weeks", () => {
    const weeks = [
      week("2026-10-05", { rated_count: 3, good_count: 1 }),
      week("2026-10-12", { rated_count: 1, good_count: 1 }),
    ];
    expect(averageGoodRate(weeks)).toBe(0.5);
    expect(averageGoodRate([])).toBeNull();
  });

  it("needs two rated weeks", () => {
    expect(insightsSummary([], 6)).toBeNull();
    expect(
      insightsSummary([week("2026-10-12", { rated_count: 3 })], 6),
    ).toBeNull();
    expect(
      insightsSummary(
        [week("2026-10-05", { rated_count: 2 }), week("2026-10-12")],
        6,
      ),
    ).toBeNull();
  });

  it("compares the last four weeks with the previous four and the average", () => {
    const weeks = [
      ...[0, 1, 2, 3].map((n) =>
        week(`2026-08-${3 + n}`, {
          rated_count: 4,
          good_count: 1,
          shown_count: 10,
          shown_rated_count: 10,
        }),
      ),
      ...[0, 1, 2, 3].map((n) =>
        week(`2026-09-${7 + n}`, {
          rated_count: 4,
          good_count: 3,
          shown_count: 10,
          shown_rated_count: 10,
        }),
      ),
    ];
    // Last four: 75%, previous four: 25%, overall: 50%.
    expect(insightsSummary(weeks, 6)).toBe(
      "Good rate over the last 4 weeks is 75% (scores of 6 or higher), up 50 points from the 4 weeks before, above the overall average of 50%.",
    );
  });

  it("mentions a rating-rate slip of at least five points", () => {
    const weeks = [
      ...[0, 1, 2, 3].map((n) =>
        week(`2026-08-${3 + n}`, {
          rated_count: 4,
          good_count: 1,
          shown_count: 10,
          shown_rated_count: 10,
        }),
      ),
      ...[0, 1, 2, 3].map((n) =>
        week(`2026-09-${7 + n}`, {
          rated_count: 4,
          good_count: 1,
          shown_count: 10,
          shown_rated_count: 2,
        }),
      ),
    ];
    const summary = insightsSummary(weeks, 6);
    expect(summary).toBe(
      "Good rate over the last 4 weeks is 25% (scores of 6 or higher), level with the 4 weeks before, matching the overall average of 25%, but the rating rate slipped to 20%.",
    );
  });

  it("stays quiet when the rating rate holds", () => {
    const weeks = [
      ...[0, 1, 2, 3].map((n) =>
        week(`2026-08-${3 + n}`, {
          rated_count: 4,
          good_count: 1,
          shown_count: 10,
          shown_rated_count: 9,
        }),
      ),
      ...[0, 1, 2, 3].map((n) =>
        week(`2026-09-${7 + n}`, {
          rated_count: 4,
          good_count: 1,
          shown_count: 10,
          shown_rated_count: 10,
        }),
      ),
    ];
    expect(insightsSummary(weeks, 6)).not.toContain("rating rate");
  });

  it("needs ratings in the last four weeks, not just somewhere", () => {
    const weeks = [
      week("2026-08-03", { rated_count: 4, good_count: 3 }),
      ...[1, 2, 3, 4, 5, 6, 7].map(() => week("2026-09-07")),
    ];
    expect(insightsSummary(weeks, 6)).toBeNull();
  });
});

describe("csv", () => {
  it("has a header and empty cells for unknown values", () => {
    expect(weeklyInsightsCsv([])).toBe(
      "week_start,rated_count,good_count,good_rate,rating_rate,model_share,curation_share,similarity_share",
    );
    expect(
      weeklyInsightsCsv([
        week("2026-10-05", { rated_count: 4, good_count: 2, good_rate: 0.5 }),
      ]),
    ).toBe(
      [
        "week_start,rated_count,good_count,good_rate,rating_rate,model_share,curation_share,similarity_share",
        "2026-10-05,4,2,0.5,,,,",
      ].join("\n"),
    );
  });

  it("numbers rates as plain decimals and keeps one row per week", () => {
    const rows = weeklyInsightsCsv([
      week("2026-10-05", {
        rated_count: 3,
        good_count: 2,
        good_rate: 2 / 3,
        rating_rate: 0.2,
        shown_count: 10,
        shown_rated_count: 2,
        score_share: { model: 0.6667, curation: 0.2, similarity: 0.1334 },
      }),
      week("2026-10-12", { rated_count: 0, score_share: null }),
    ]).split("\n");
    expect(rows).toEqual([
      "week_start,rated_count,good_count,good_rate,rating_rate,model_share,curation_share,similarity_share",
      "2026-10-05,3,2,0.67,0.2,0.67,0.2,0.13",
      "2026-10-12,0,0,,,,,",
    ]);
  });

  it("keeps the given (oldest first) order", () => {
    expect(
      weeklyInsightsCsv([week("2026-10-12"), week("2026-10-05")]).split("\n"),
    ).toEqual([
      "week_start,rated_count,good_count,good_rate,rating_rate,model_share,curation_share,similarity_share",
      "2026-10-12,0,0,,,,,",
      "2026-10-05,0,0,,,,,",
    ]);
  });
});
