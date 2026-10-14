import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import {
  formatPercent,
  formatWeek,
  labelStride,
  plural,
  trendPath,
  trendPoints,
  type ChartBox,
} from "#/lib/insights";
import type { WeekInsights } from "#/server/insights";

import {
  areaPath,
  describeWeekRates,
  seriesPoints,
} from "./GoodRateTrendHelpers";

// The width is the rendered one once measured, so text stays at 12px however
// wide the page is; 640 is what the server renders with.
const DEFAULT_WIDTH = 640;
const MARGINS = { height: 240, left: 44, right: 20, top: 24, bottom: 32 };
const GRID = [0, 0.25, 0.5, 0.75, 1];
// Leave at least this much room per x-axis label ("Sep 28" is about 40px).
const LABEL_GAP = 64;

/**
 * Weekly good rate as a line chart (inline SVG). Weeks without ratings
 * break the line. Hovering a week, or focusing the chart and using the arrow
 * keys, shows its numbers; the same numbers are in the table on the insights
 * page, and in the chart's description for screen readers. With
 * `showRatingRate`, the week's rating rate is overlayed as a dashed line and
 * both series are described.
 */
export function GoodRateTrend({
  weeks,
  goodThreshold,
  showRatingRate = false,
}: {
  weeks: readonly WeekInsights[];
  goodThreshold: number;
  showRatingRate?: boolean;
}) {
  const titleId = useId();
  const descId = useId();
  // Colon-free: the id goes into fill="url(#…)", where `:` is not an id char.
  const areaGradientId = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const figureRef = useRef<HTMLElement>(null);
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [active, setActive] = useState<number | null>(null);

  useEffect(() => {
    const figure = figureRef.current;
    if (!figure) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.max(240, Math.round(entry.contentRect.width)));
    });
    observer.observe(figure);
    return () => observer.disconnect();
  }, []);

  const box: ChartBox = { width, ...MARGINS };
  const points = trendPoints(weeks, box);
  const plotWidth = box.width - box.left - box.right;
  const plotBottom = box.height - box.bottom;
  const plotHeight = plotBottom - box.top;
  const columnWidth =
    weeks.length > 1 ? plotWidth / (weeks.length - 1) : plotWidth;
  const stride = labelStride(points.length, plotWidth, LABEL_GAP);
  const rated = points.filter((point) => point.y != null);
  const latest = rated.at(-1);
  const current = active == null ? null : points[active];
  // Same x layout, the week's rating rate; null weeks break the series.
  const ratingPoints = showRatingRate
    ? seriesPoints(points, box, (week) => week.rating_rate)
    : [];

  function onKeyDown(event: KeyboardEvent<SVGSVGElement>) {
    const last = points.length - 1;
    const from = active ?? last;
    const next =
      event.key === "ArrowLeft"
        ? Math.max(0, from - 1)
        : event.key === "ArrowRight"
          ? Math.min(last, from + 1)
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? last
              : null;
    if (next == null) return;
    event.preventDefault();
    setActive(next);
  }

  return (
    <figure ref={figureRef} className="flex min-w-0 flex-col gap-2">
      <svg
        viewBox={`0 0 ${box.width} ${box.height}`}
        role="img"
        aria-labelledby={titleId}
        aria-describedby={descId}
        tabIndex={0}
        className="h-auto w-full overflow-visible rounded-lg text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        onMouseLeave={() => setActive(null)}
        onFocus={() => setActive(points.length > 0 ? points.length - 1 : null)}
        onBlur={() => setActive(null)}
        onKeyDown={onKeyDown}
      >
        <title id={titleId}>
          Weekly good rate{showRatingRate ? " and rating rate" : ""}
        </title>
        <desc id={descId}>
          {rated.length === 0
            ? "No ratings in these weeks yet."
            : rated
                .map(
                  ({ week }) =>
                    `Week of ${formatWeek(week.week_start)}: ${describeWeekRates(week, { ratingRate: showRatingRate })}`,
                )
                .join("; ")}
        </desc>
        <defs>
          <linearGradient
            id={areaGradientId}
            x1={0}
            y1={box.top}
            x2={0}
            y2={plotBottom}
            gradientUnits="userSpaceOnUse"
          >
            <stop
              offset={0}
              style={{ stopColor: "var(--chart-1)", stopOpacity: 0.18 }}
            />
            <stop
              offset={1}
              style={{ stopColor: "var(--chart-1)", stopOpacity: 0 }}
            />
          </linearGradient>
        </defs>
        {GRID.map((rate) => {
          const y = box.top + (1 - rate) * plotHeight;
          return (
            <g key={rate}>
              <line
                x1={box.left}
                x2={box.width - box.right}
                y1={y}
                y2={y}
                stroke="currentColor"
                strokeOpacity={rate === 0 ? 0.5 : 0.15}
              />
              <text
                x={box.left - 8}
                y={y}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={12}
                fill="currentColor"
                className="tabular-nums"
              >
                {formatPercent(rate)}
              </text>
            </g>
          );
        })}
        {points.map(({ x, week }, index) =>
          // Counting back from the latest week, so it always has a label.
          (points.length - 1 - index) % stride === 0 ? (
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
        {/*
          The crosshair marks the latest week even when nothing is hovered; a
          hovered or focused week moves it there.
        */}
        {(current ?? latest) && (
          <line
            x1={(current ?? latest)!.x}
            x2={(current ?? latest)!.x}
            y1={box.top}
            y2={plotBottom}
            stroke="currentColor"
            strokeOpacity={0.4}
          />
        )}
        {/* The area fills only over consecutive rated weeks, like the line. */}
        <path
          d={areaPath(points, plotBottom)}
          fill={`url(#${areaGradientId})`}
          className="stroke-none"
        />
        <path
          d={trendPath(points)}
          fill="none"
          className="stroke-chart-1"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {showRatingRate && (
          <path
            d={trendPath(ratingPoints)}
            fill="none"
            className="stroke-chart-2"
            strokeWidth={1.5}
            strokeDasharray="4 4"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        )}
        {rated.map(({ x, y, week }) => (
          <circle
            key={week.week_start}
            cx={x}
            cy={y ?? 0}
            r={current?.week === week || week === latest?.week ? 5 : 4}
            className="fill-chart-1 stroke-background"
            strokeWidth={2}
          />
        ))}
        {showRatingRate &&
          ratingPoints
            .filter((point) => point.y != null)
            .map(({ x, y, week }) => (
              <circle
                key={week.week_start}
                cx={x}
                cy={y ?? 0}
                r={current?.week === week || week === latest?.week ? 4 : 3}
                className="fill-chart-2 stroke-background"
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
            y={box.top}
            width={columnWidth}
            height={plotHeight}
            fill="transparent"
            onMouseEnter={() => setActive(index)}
          />
        ))}
      </svg>
      <p
        className="min-h-5 text-sm text-foreground tabular-nums"
        aria-hidden="true"
      >
        {current ? (
          <>
            <span className="font-medium">
              Week of {formatWeek(current.week.week_start)}:
            </span>{" "}
            {current.week.good_rate == null
              ? "no ratings"
              : `${formatPercent(current.week.good_rate)} good (${current.week.good_count} of ${plural(current.week.rated_count, "rating")})`}
            {showRatingRate &&
              current.week.rating_rate != null &&
              ` · ${formatPercent(current.week.rating_rate)} rated`}
          </>
        ) : (
          <span className="text-muted-foreground">
            Hover a week, or focus the chart and use the arrow keys, to see its
            numbers.
          </span>
        )}
      </p>
      {showRatingRate && (
        // The chart's description explains the series to screen readers, so
        // this visible row is hidden from them and only labels the swatches:
        // the dashed shape already differs, color does the rest for sight.
        <div
          className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground"
          aria-hidden="true"
        >
          <span className="flex items-center gap-1.5">
            <svg
              width={16}
              height={6}
              viewBox="0 0 16 6"
              aria-hidden="true"
              className="shrink-0"
            >
              <line
                x1={0}
                y1={3}
                x2={16}
                y2={3}
                className="stroke-chart-1"
                strokeWidth={2}
              />
            </svg>
            Good rate
          </span>
          <span className="flex items-center gap-1.5">
            <svg
              width={16}
              height={6}
              viewBox="0 0 16 6"
              aria-hidden="true"
              className="shrink-0"
            >
              <line
                x1={0}
                y1={3}
                x2={16}
                y2={3}
                className="stroke-chart-2"
                strokeWidth={1.5}
                strokeDasharray="4 4"
              />
            </svg>
            Rating rate
          </span>
        </div>
      )}
      <figcaption className="text-sm text-muted-foreground">
        Share of each week&apos;s new ratings scored {goodThreshold} or higher.
        Weeks without ratings leave a gap.
      </figcaption>
    </figure>
  );
}
