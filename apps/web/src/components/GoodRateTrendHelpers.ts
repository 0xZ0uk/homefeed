import type { ChartBox, TrendPoint } from "#/lib/insights";
import { formatPercent } from "#/lib/insights";
import type { WeekInsights } from "#/server/insights";

/**
 * `trendPoints` is week-indexed, so its x layout works for any per-week rate:
 * give `rate` the value to plot and null-safe weeks still break the series
 * the way `trendPath` expects. Used for the optional rating-rate overlay.
 */
export function seriesPoints(
  points: readonly TrendPoint[],
  box: ChartBox,
  rate: (week: WeekInsights) => number | null,
): TrendPoint[] {
  const plotHeight = box.height - box.top - box.bottom;
  return points.map((point) => {
    const value = rate(point.week);
    return {
      ...point,
      y: value == null ? null : box.top + (1 - value) * plotHeight,
    };
  });
}

/**
 * A closed path under every run of consecutive rated weeks: down to the plot
 * bottom at each end of a run; a null week starts a new one, matching
 * `trendPath`'s gaps. Single rated weeks produce a thin sliver, not a
 * horizontal line.
 */
export function areaPath(
  points: readonly TrendPoint[],
  plotBottom: number,
): string {
  const segments: string[] = [];
  let open = false;
  let lastX = 0;
  for (const { x, y } of points) {
    if (y == null) {
      if (open) {
        segments.push(`L${round(lastX)} ${round(plotBottom)} Z`);
        open = false;
      }
      continue;
    }
    segments.push(
      open
        ? `L${round(x)} ${round(y)}`
        : `M${round(x)} ${round(plotBottom)} L${round(x)} ${round(y)}`,
    );
    open = true;
    lastX = x;
  }
  if (open) segments.push(`L${round(lastX)} ${round(plotBottom)} Z`);
  return segments.join(" ");
}

/**
 * One week for the chart's description, both series when the overlay is on:
 * a null `good_rate` means nothing was rated, a null `rating_rate` means no
 * feed was built that week.
 */
export function describeWeekRates(
  week: WeekInsights,
  { ratingRate }: { ratingRate: boolean },
): string {
  const parts = [
    week.good_rate == null
      ? "no ratings"
      : `${formatPercent(week.good_rate)} good`,
  ];
  if (ratingRate) {
    parts.push(
      week.rating_rate == null
        ? "no feed"
        : `${formatPercent(week.rating_rate)} rated`,
    );
  }
  return parts.join(", ");
}

function round(value: number): number {
  return Math.round(value * 10) / 10;
}
