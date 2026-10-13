import { useId, useState } from "react";

import {
  formatPercent,
  formatWeek,
  plural,
  trendPath,
  trendPoints,
  type ChartBox,
} from "#/lib/insights";
import type { WeekInsights } from "#/server/insights";

const BOX: ChartBox = {
  width: 640,
  height: 240,
  left: 44,
  right: 16,
  top: 16,
  bottom: 32,
};
const GRID = [0, 0.25, 0.5, 0.75, 1];

/**
 * Weekly good rate as a line chart (inline SVG). Weeks without ratings
 * break the line. Hovering a week shows its numbers; the same numbers are in
 * the table on the insights page for keyboard and screen-reader users.
 */
export function GoodRateTrend({ weeks }: { weeks: readonly WeekInsights[] }) {
  const titleId = useId();
  const descId = useId();
  const [hovered, setHovered] = useState<number | null>(null);
  const points = trendPoints(weeks, BOX);
  const plotBottom = BOX.height - BOX.bottom;
  const plotHeight = plotBottom - BOX.top;
  const columnWidth =
    weeks.length > 1
      ? (BOX.width - BOX.left - BOX.right) / (weeks.length - 1)
      : BOX.width - BOX.left - BOX.right;
  const rated = points.filter((point) => point.y != null);
  const latest = rated.at(-1);
  const active = hovered == null ? null : points[hovered];

  return (
    <figure className="flex flex-col gap-2">
      <svg
        viewBox={`0 0 ${BOX.width} ${BOX.height}`}
        role="img"
        aria-labelledby={titleId}
        aria-describedby={descId}
        className="h-auto w-full overflow-visible text-muted-foreground"
        onMouseLeave={() => setHovered(null)}
      >
        <title id={titleId}>Weekly good rate</title>
        <desc id={descId}>
          {rated.length === 0
            ? "No ratings in these weeks yet."
            : rated
                .map(
                  ({ week }) =>
                    `Week of ${formatWeek(week.week_start)}: ${formatPercent(week.good_rate)}`,
                )
                .join("; ")}
        </desc>
        {GRID.map((rate) => {
          const y = BOX.top + (1 - rate) * plotHeight;
          return (
            <g key={rate}>
              <line
                x1={BOX.left}
                x2={BOX.width - BOX.right}
                y1={y}
                y2={y}
                stroke="currentColor"
                strokeOpacity={rate === 0 ? 0.5 : 0.15}
              />
              <text
                x={BOX.left - 8}
                y={y}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={12}
                fill="currentColor"
              >
                {formatPercent(rate)}
              </text>
            </g>
          );
        })}
        {points.map(({ x, week }, index) =>
          // Every other week, counting back from the latest, so labels don't collide.
          (points.length - 1 - index) % 2 === 0 ? (
            <text
              key={week.week_start}
              x={x}
              y={plotBottom + 20}
              textAnchor="middle"
              fontSize={12}
              fill="currentColor"
            >
              {formatWeek(week.week_start)}
            </text>
          ) : null,
        )}
        {active && (
          <line
            x1={active.x}
            x2={active.x}
            y1={BOX.top}
            y2={plotBottom}
            stroke="currentColor"
            strokeOpacity={0.4}
          />
        )}
        <path
          d={trendPath(points)}
          fill="none"
          className="stroke-chart-1"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {rated.map(({ x, y, week }) => (
          <circle
            key={week.week_start}
            cx={x}
            cy={y ?? 0}
            r={active?.week === week || week === latest?.week ? 5 : 4}
            className="fill-chart-1 stroke-background"
            strokeWidth={2}
          />
        ))}
        {latest && latest.y != null && (
          <text
            x={latest.x}
            y={latest.y - 12}
            textAnchor="middle"
            fontSize={12}
            fontWeight={600}
            className="fill-foreground"
          >
            {formatPercent(latest.week.good_rate)}
          </text>
        )}
        {points.map(({ x, week }, index) => (
          <rect
            key={week.week_start}
            x={x - columnWidth / 2}
            y={BOX.top}
            width={columnWidth}
            height={plotHeight}
            fill="transparent"
            onMouseEnter={() => setHovered(index)}
          />
        ))}
      </svg>
      <p className="min-h-5 text-sm text-muted-foreground" aria-hidden="true">
        {active
          ? `Week of ${formatWeek(active.week.week_start)}: ${
              active.week.good_rate == null
                ? "no ratings"
                : `${formatPercent(active.week.good_rate)} good (${active.week.good_count} of ${plural(active.week.rated_count, "rating")})`
            }`
          : "Hover a week for its numbers."}
      </p>
      <figcaption className="text-sm text-muted-foreground">
        Share of each week's new ratings that are B-- or higher. Weeks without
        ratings leave a gap.
      </figcaption>
    </figure>
  );
}
