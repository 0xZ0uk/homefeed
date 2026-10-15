import type { WeekInsightsOut } from "@homefeed/api-client";

/** Pure helpers for the insights page: formatting, totals and chart geometry. */

/** A rate in [0, 1] as a whole percentage, e.g. "62%", or "–" when unknown. */
export function formatPercent(rate: number | null | undefined): string {
  if (rate == null || !Number.isFinite(rate)) return "–";
  return `${Math.round(rate * 100)}%`;
}

/** A date (`YYYY-MM-DD`) as e.g. "Oct 5". */
export function formatDay(day: string): string {
  const parsed = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return day;
  return parsed.toLocaleDateString("en", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** A week's Monday (`YYYY-MM-DD`) as e.g. "Oct 5". */
export function formatWeek(weekStart: string): string {
  return formatDay(weekStart);
}

/** `count` and the noun, pluralized: "1 rating", "3 ratings". */
export function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** Ratings per whole score over all `weeks`, best score (10) first. */
export function totalScoreCounts(
  weeks: readonly WeekInsightsOut[],
): { score: number; count: number }[] {
  const totals = new Map<number, number>();
  for (const week of weeks) {
    for (const { score, count } of week.score_counts) {
      totals.set(score, (totals.get(score) ?? 0) + count);
    }
  }
  return [...totals].map(([score, count]) => ({ score, count }));
}

/** Whether ratings of `score` count as good. */
export function isGoodBucket(score: number, goodThreshold: number): boolean {
  return score >= goodThreshold;
}

/** Good rate over all `weeks` (good ratings / ratings), or null. */
export function overallGoodRate(
  weeks: readonly WeekInsightsOut[],
): number | null {
  const rated = weeks.reduce((sum, week) => sum + week.rated_count, 0);
  const good = weeks.reduce((sum, week) => sum + week.good_count, 0);
  return rated > 0 ? good / rated : null;
}

/** Rating rate over all `weeks` (rated shown videos / shown videos), or null. */
export function overallRatingRate(
  weeks: readonly WeekInsightsOut[],
): number | null {
  const shown = weeks.reduce((sum, week) => sum + week.shown_count, 0);
  const rated = weeks.reduce((sum, week) => sum + week.shown_rated_count, 0);
  return shown > 0 ? rated / shown : null;
}

/** Week spans the insights page can switch between. */
export type WeekRange = 4 | 12 | 26 | 52;

export const WEEK_RANGES: readonly WeekRange[] = [4, 12, 26, 52];

export const DEFAULT_WEEK_RANGE: WeekRange = 12;

/**
 * A valid week span from untrusted input: numbers or numeric strings
 * matching one of `WEEK_RANGES`, else `DEFAULT_WEEK_RANGE`.
 */
export function parseWeekRange(value: unknown): WeekRange {
  const weeks =
    typeof value === "number"
      ? value
      : typeof value === "string" && value.trim() !== ""
        ? Number(value)
        : NaN;
  return WEEK_RANGES.includes(weeks as WeekRange)
    ? (weeks as WeekRange)
    : DEFAULT_WEEK_RANGE;
}

/** The last `n` items, or all of them when there are fewer. */
export function lastN<T>(items: readonly T[], n: number): readonly T[] {
  return n <= 0 ? [] : items.slice(-Math.floor(n));
}

/**
 * `current` minus `baseline` in percentage points, rounded to a whole point;
 * null when either rate is unknown.
 */
export function deltaPoints(
  current: number | null | undefined,
  baseline: number | null | undefined,
): number | null {
  if (
    current == null ||
    baseline == null ||
    !Number.isFinite(current) ||
    !Number.isFinite(baseline)
  ) {
    return null;
  }
  return Math.round((current - baseline) * 100);
}

/** The window before the compared one, of the same length. */
function previousWindow<T>(weeks: readonly T[], window: number): readonly T[] {
  return weeks.slice(
    Math.max(0, weeks.length - window * 2),
    Math.max(0, weeks.length - window),
  );
}

export interface ChartBox {
  width: number;
  height: number;
  /** Space for axis labels: left, right, top and bottom. */
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export interface TrendPoint {
  x: number;
  /** Null for weeks with no ratings: the line has a gap there. */
  y: number | null;
  week: WeekInsightsOut;
}

/**
 * Where each week's good rate goes in the chart: weeks spread evenly
 * left to right, rates 0–100% bottom to top.
 */
export function trendPoints(
  weeks: readonly WeekInsightsOut[],
  box: ChartBox,
): TrendPoint[] {
  const plotWidth = box.width - box.left - box.right;
  const plotHeight = box.height - box.top - box.bottom;
  const step = weeks.length > 1 ? plotWidth / (weeks.length - 1) : 0;
  return weeks.map((week, index) => ({
    x: box.left + (weeks.length > 1 ? index * step : plotWidth / 2),
    y:
      week.good_rate == null
        ? null
        : box.top + (1 - week.good_rate) * plotHeight,
    week,
  }));
}

/**
 * SVG path data joining consecutive points that have a rate; a week without
 * one breaks the line rather than being drawn as 0%.
 */
export function trendPath(points: readonly TrendPoint[]): string {
  const commands: string[] = [];
  let drawing = false;
  for (const { x, y } of points) {
    if (y == null) {
      drawing = false;
      continue;
    }
    commands.push(`${drawing ? "L" : "M"}${round(x)} ${round(y)}`);
    drawing = true;
  }
  return commands.join(" ");
}

/**
 * Label every `n`th week on the x axis, the smallest `n` that keeps labels at
 * least `minGap` apart over `plotWidth`.
 */
export function labelStride(
  count: number,
  plotWidth: number,
  minGap: number,
): number {
  if (count < 2) return 1;
  const step = plotWidth / (count - 1);
  return Math.max(1, Math.ceil(minGap / step));
}

/**
 * Overall model share over all `weeks`: the pooled mean of each week's share,
 * ignoring weeks without one; null when none of them has a share.
 */
export function overallModelShare(
  weeks: readonly WeekInsightsOut[],
): number | null {
  const shares = weeks
    .map((week) => week.score_share?.model)
    .filter((share): share is number => share != null);
  return shares.length === 0
    ? null
    : shares.reduce((sum, share) => sum + share, 0) / shares.length;
}

/** The good rate over the last `window` weeks versus the window before it. */
export function goodRateDelta(
  weeks: readonly WeekInsightsOut[],
  window = 4,
): number | null {
  return deltaPoints(
    overallGoodRate(lastN(weeks, window)),
    overallGoodRate(previousWindow(weeks, window)),
  );
}

/** The rating rate over the last `window` weeks versus the window before it. */
export function ratingRateDelta(
  weeks: readonly WeekInsightsOut[],
  window = 4,
): number | null {
  return deltaPoints(
    overallRatingRate(lastN(weeks, window)),
    overallRatingRate(previousWindow(weeks, window)),
  );
}

/** The model share over the last `window` weeks versus the window before it. */
export function modelShareDelta(
  weeks: readonly WeekInsightsOut[],
  window = 4,
): number | null {
  return deltaPoints(
    overallModelShare(lastN(weeks, window)),
    overallModelShare(previousWindow(weeks, window)),
  );
}

/**
 * One human sentence about the last weeks, or null when fewer than two weeks
 * have ratings or the last four have none. Compares the last-4-week good rate
 * with the previous four and with the overall average, and mentions the
 * rating rate only when it slipped by at least five points.
 */
export function insightsSummary(
  weeks: readonly WeekInsightsOut[],
  goodThreshold: number,
): string | null {
  if (weeks.filter((week) => week.rated_count > 0).length < 2) return null;
  const rate = overallGoodRate(lastN(weeks, 4));
  if (rate == null) return null;
  const recent = goodRateDelta(weeks);
  const trend =
    recent == null
      ? ""
      : recent === 0
        ? ", level with the 4 weeks before"
        : `, ${recent > 0 ? "up" : "down"} ${Math.abs(recent)} points from the 4 weeks before`;
  const average = averageGoodRate(weeks);
  const versus =
    average == null ? "" : versusAverage(deltaPoints(rate, average), average);
  const rating = ratingRateDelta(weeks);
  const slippage =
    rating != null && rating <= -5
      ? `, but the rating rate slipped to ${formatPercent(overallRatingRate(lastN(weeks, 4)))}`
      : "";
  return `Good rate over the last 4 weeks is ${formatPercent(rate)} (scores of ${goodThreshold} or higher)${trend}${versus}${slippage}.`;
}

/** How the last window compares with the pooled average. */
function versusAverage(delta: number | null, average: number): string {
  if (delta == null) return "";
  if (delta === 0) {
    return `, matching the overall average of ${formatPercent(average)}`;
  }
  return `, ${delta > 0 ? "above" : "below"} the overall average of ${formatPercent(average)}`;
}

/** Good rate over all `weeks` pooled together, or null. */
export function averageGoodRate(
  weeks: readonly WeekInsightsOut[],
): number | null {
  return overallGoodRate(weeks);
}

/** One row per week, oldest first, for a spreadsheet. */
export function weeklyInsightsCsv(weeks: readonly WeekInsightsOut[]): string {
  const columns = (week: WeekInsightsOut): string[] => [
    week.week_start,
    `${week.rated_count}`,
    `${week.good_count}`,
    rateCell(week.good_rate),
    rateCell(week.rating_rate),
    rateCell(week.score_share?.model),
    rateCell(week.score_share?.curation),
    rateCell(week.score_share?.similarity),
  ];
  return [
    "week_start,rated_count,good_count,good_rate,rating_rate,model_share,curation_share,similarity_share",
    ...weeks.map(columns).map((cells) => cells.join(",")),
  ].join("\n");
}

/** A rate as a plain number rounded to two decimals (0.67), or empty. */
function rateCell(value: number | null | undefined): string {
  return value == null ? "" : `${Math.round(value * 100) / 100}`;
}

function round(value: number): number {
  return Math.round(value * 10) / 10;
}
