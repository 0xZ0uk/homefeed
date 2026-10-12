import type { WeekInsightsOut } from "@homefeed/api-client";

/** Pure helpers for the insights page: formatting, totals and chart geometry. */

/** A rate in [0, 1] as a whole percentage, e.g. "62%", or "–" when unknown. */
export function formatPercent(rate: number | null | undefined): string {
  if (rate == null || !Number.isFinite(rate)) return "–";
  return `${Math.round(rate * 100)}%`;
}

/** A week's Monday (`YYYY-MM-DD`) as e.g. "Oct 5". */
export function formatWeek(weekStart: string): string {
  const parsed = new Date(`${weekStart}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return weekStart;
  return parsed.toLocaleDateString("en", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** `count` and the noun, pluralized: "1 rating", "3 ratings". */
export function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** Ratings per tier over all `weeks`, best tier first. */
export function totalTierCounts(
  weeks: readonly WeekInsightsOut[],
): { tier: string; count: number }[] {
  const totals = new Map<string, number>();
  for (const week of weeks) {
    for (const { tier, count } of week.tier_counts) {
      totals.set(tier, (totals.get(tier) ?? 0) + count);
    }
  }
  return [...totals].map(([tier, count]) => ({ tier, count }));
}

/** Good-tier rate over all `weeks` (good ratings / ratings), or null. */
export function overallGoodTierRate(
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
 * Where each week's good-tier rate goes in the chart: weeks spread evenly
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
      week.good_tier_rate == null
        ? null
        : box.top + (1 - week.good_tier_rate) * plotHeight,
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

function round(value: number): number {
  return Math.round(value * 10) / 10;
}
