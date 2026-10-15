import {
  useQueryErrorResetBoundary,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { Link, createFileRoute, useRouter } from "@tanstack/react-router";
import {
  ChartNoAxesColumn,
  ChevronDown,
  Download,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";

import { AppShell } from "#/components/AppShell";
import { DiscoveryRecap, RecapSkeleton } from "#/components/DiscoveryRecap";
import { GoodRateTrend } from "#/components/GoodRateTrend";
import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "#/components/ui/card";
import {
  formatPercent,
  formatWeek,
  goodRateDelta,
  insightsSummary,
  isGoodBucket,
  lastN,
  modelShareDelta,
  overallGoodRate,
  overallRatingRate,
  parseWeekRange,
  plural,
  ratingRateDelta,
  totalScoreCounts,
  WEEK_RANGES,
  weeklyInsightsCsv,
  type WeekRange,
} from "#/lib/insights";
import { ScoreFace } from "#/components/ScoreFace";
import { scoreLabel } from "#/lib/scores";
import { cn } from "#/lib/utils";
import {
  discoveryRecapQuery,
  weeklyInsightsQuery,
  type WeekInsights,
} from "#/server/insights";

/**
 * Whether the feed is working, by the success metric rather than watch time,
 * and whether discovery is: the week's recap of new channels and topics tops
 * the page.
 */
export const Route = createFileRoute("/insights")({
  validateSearch: (search: Record<string, unknown>): { weeks: WeekRange } => ({
    weeks: parseWeekRange(search.weeks),
  }),
  head: () => ({ meta: [{ title: "Insights · Homefeed" }] }),
  loaderDeps: ({ search }) => ({ weeks: search.weeks }),
  loader: async ({ context: { queryClient }, deps }) => {
    // The recap is extra: it doesn't hold up or break the rest of the page
    // (see DiscoveryRecap).
    await Promise.all([
      queryClient.ensureQueryData(weeklyInsightsQuery(deps.weeks)),
      queryClient.prefetchQuery(discoveryRecapQuery),
    ]);
  },
  pendingComponent: InsightsPending,
  component: Insights,
  errorComponent: InsightsError,
});

// Categorical chart slots 1–3 (see `--chart-*` in styles.css), in a fixed order.
const SHARES = [
  { key: "model", label: "Model", swatch: "bg-chart-1" },
  {
    key: "curation",
    label: "Subscriptions (channels, tags)",
    swatch: "bg-chart-2",
  },
  { key: "similarity", label: "Similarity to ratings", swatch: "bg-chart-3" },
] as const;

/** How many weeks a stat card's sparkline covers. */
const SPARKLINE_WEEKS = 8;

function Insights() {
  const { weeks } = Route.useSearch();
  const { data } = useSuspenseQuery(weeklyInsightsQuery(weeks));
  const allWeeks = data.weeks;
  const thisWeek = allWeeks.at(-1);
  const summary = insightsSummary(allWeeks, data.good_threshold);
  const hasRatings = allWeeks.some((week) => week.rated_count > 0);
  const [showRatingRate, setShowRatingRate] = useState(false);

  function downloadCsv() {
    const blob = new Blob([weeklyInsightsCsv(allWeeks)], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `insights-weekly-${weeks}wk.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <AppShell className="flex max-w-5xl flex-col gap-10">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
        <div className="flex max-w-prose flex-col gap-1">
          <h1 className="text-xl font-semibold">Insights</h1>
          <p className="text-pretty text-muted-foreground">
            Is the feed working? The measure is the good rate: the share of
            rated videos scored {data.good_threshold} or higher. Last {weeks}{" "}
            weeks.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <nav aria-label="Time window">
            <div className="flex gap-0.5 rounded-full bg-secondary p-1">
              {WEEK_RANGES.map((range) => {
                const current = range === weeks;
                return (
                  <Link
                    key={range}
                    to="/insights"
                    search={{ weeks: range }}
                    aria-current={current ? "page" : undefined}
                    className={cn(
                      "flex h-7 items-center rounded-full px-3 text-sm font-medium whitespace-nowrap outline-none transition-colors duration-150 focus-visible:ring-3 focus-visible:ring-ring/50",
                      current
                        ? "bg-card text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {range} wk
                  </Link>
                );
              })}
            </div>
          </nav>
          <Button
            variant="secondary"
            onClick={downloadCsv}
            aria-label="Download weekly insights as CSV"
          >
            <Download aria-hidden="true" data-icon="inline-start" />
            CSV
          </Button>
        </div>
      </header>

      <DiscoveryRecap />

      {summary && (
        <Card className="flex-row items-start gap-3 bg-accent p-4 text-sm">
          <Sparkles
            aria-hidden="true"
            className="mt-0.5 size-4 shrink-0 text-brand"
          />
          <p className="min-w-0 max-w-prose text-pretty">{summary}</p>
        </Card>
      )}

      {thisWeek && (
        <section aria-labelledby="this-week-heading">
          <h2 id="this-week-heading" className="text-lg font-semibold">
            This week{" "}
            <span className="font-normal text-muted-foreground">
              (from {formatWeek(thisWeek.week_start)})
            </span>
          </h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <StatCard
              label="Good rate"
              rate={thisWeek.good_rate}
              detail={
                thisWeek.rated_count > 0
                  ? `${thisWeek.good_count} of ${plural(thisWeek.rated_count, "rating")}`
                  : "No ratings yet"
              }
              delta={goodRateDelta(allWeeks)}
              series={lastN(allWeeks, SPARKLINE_WEEKS).map(
                (week) => week.good_rate,
              )}
              seriesClass="text-chart-1"
            />
            <StatCard
              label="Rating rate"
              rate={thisWeek.rating_rate}
              detail={
                thisWeek.shown_count > 0
                  ? `${thisWeek.shown_rated_count} of ${plural(thisWeek.shown_count, "video")} shown`
                  : "No feed yet"
              }
              delta={ratingRateDelta(allWeeks)}
              series={lastN(allWeeks, SPARKLINE_WEEKS).map(
                (week) => week.rating_rate,
              )}
              seriesClass="text-chart-2"
            />
            <StatCard
              label="Model share"
              rate={thisWeek.score_share?.model}
              detail={
                thisWeek.feed_count > 0
                  ? `${thisWeek.model_feed_count} of ${plural(thisWeek.feed_count, "feed")} used a model`
                  : "No feed yet"
              }
              delta={modelShareDelta(allWeeks)}
              series={lastN(allWeeks, SPARKLINE_WEEKS).map(
                (week) => week.score_share?.model ?? null,
              )}
              seriesClass="text-chart-3"
            />
          </div>
        </section>
      )}

      <Panel
        id="trend-heading"
        title="Good rate by week"
        description={`Over ${weeks} weeks: good rate ${formatPercent(overallGoodRate(allWeeks))}, rating rate ${formatPercent(overallRatingRate(allWeeks))}.`}
        action={
          <Button
            variant={showRatingRate ? "secondary" : "outline"}
            size="sm"
            aria-pressed={showRatingRate}
            onClick={() => setShowRatingRate((show) => !show)}
          >
            Rating rate
          </Button>
        }
      >
        {hasRatings ? (
          <GoodRateTrend
            weeks={allWeeks}
            goodThreshold={data.good_threshold}
            showRatingRate={showRatingRate}
          />
        ) : (
          <EmptyState icon={ChartNoAxesColumn}>
            No ratings in the last {weeks} weeks yet. Rate videos from your{" "}
            <Link
              to="/"
              className="underline underline-offset-2 hover:text-foreground"
            >
              feed
            </Link>{" "}
            and the weekly good rate appears here.
          </EmptyState>
        )}
      </Panel>

      <ScoreDistribution weeks={allWeeks} goodThreshold={data.good_threshold} />
      <ScoreShares weeks={allWeeks} />
      <WeekTable weeks={allWeeks} currentWeek={thisWeek} />
    </AppShell>
  );
}

/** A titled panel: heading and description in the card, content below. */
function Panel({
  id,
  title,
  description,
  action,
  children,
}: {
  id: string;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card aria-labelledby={id}>
      <CardHeader
        className={cn(
          action && "flex-row items-start justify-between gap-x-4 gap-y-2",
        )}
      >
        <div className="flex min-w-0 flex-col gap-1">
          <CardTitle render={<h2 id={id} />} className="text-lg">
            {title}
          </CardTitle>
          {description && (
            <CardDescription className="max-w-prose text-pretty">
              {description}
            </CardDescription>
          )}
        </div>
        {action}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

/** One "this week" figure: label, delta, big value, detail and sparkline. */
function StatCard({
  label,
  rate,
  detail,
  delta,
  series,
  seriesClass,
}: {
  label: string;
  rate: number | null | undefined;
  detail: string;
  delta: number | null;
  series: readonly (number | null)[];
  seriesClass: string;
}) {
  return (
    <Card className="gap-3 p-5">
      <dl className="flex flex-col gap-2">
        <div className="flex min-h-5 items-start justify-between gap-2">
          <dt className="text-sm font-medium text-muted-foreground">{label}</dt>
          <DeltaBadge delta={delta} />
        </div>
        <dd
          className={cn(
            "text-3xl leading-tight font-semibold tabular-nums tracking-tight",
            rate == null && "text-muted-foreground",
          )}
        >
          {formatPercent(rate)}
        </dd>
        <dd className="text-sm text-muted-foreground">{detail}</dd>
      </dl>
      <Sparkline values={series} className={seriesClass} />
    </Card>
  );
}

/**
 * A whole-percentage-point change versus the previous window, as a chip.
 * Nothing to compare yet renders nothing: the detail line already says why.
 */
function DeltaBadge({ delta }: { delta: number | null }) {
  if (delta == null) return null;
  const rounded = Math.round(delta);
  const context = <span className="sr-only"> versus the previous 4 weeks</span>;
  if (rounded === 0) {
    return (
      <Badge variant="outline" className="text-muted-foreground tabular-nums">
        0 pts
        {context}
      </Badge>
    );
  }
  const up = rounded > 0;
  return (
    <Badge
      variant="outline"
      className={cn("tabular-nums", up ? "text-success" : "text-destructive")}
    >
      <span aria-hidden="true">{up ? "▲" : "▼"}</span>
      {`${up ? "+" : "−"}${Math.abs(rounded)} pts`}
      {context}
    </Badge>
  );
}

/**
 * The last few weeks of a series as a tiny line (decorative; the same numbers
 * are in the table and chart panels). Weeks without a value break the line.
 */
function Sparkline({
  values,
  className,
}: {
  values: readonly (number | null)[];
  className?: string;
}) {
  const width = 64;
  const height = 20;
  const pad = 1;
  const count = values.length;
  if (count < 2) return null;
  const points = values.map((value, index) => {
    if (value == null) return null;
    const clamped = Math.min(1, Math.max(0, value));
    return {
      x: pad + (index / (count - 1)) * (width - 2 * pad),
      y: pad + (1 - clamped) * (height - 2 * pad),
    };
  });
  const commands: string[] = [];
  let drawing = false;
  for (const point of points) {
    if (!point) {
      drawing = false;
      continue;
    }
    commands.push(
      `${drawing ? "L" : "M"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`,
    );
    drawing = true;
  }
  // Nothing to join yet (one week, or only isolated weeks): no empty strip.
  if (!commands.some((command) => command.startsWith("L"))) return null;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      fill="none"
      className={cn("h-5 w-full overflow-visible", className)}
    >
      <path
        d={commands.join(" ")}
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** A colour key for a chart: a swatch beside each label. */
function Legend({
  items,
}: {
  items: readonly { label: string; swatch: string }[];
}) {
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
      {items.map(({ label, swatch }) => (
        <li key={label} className="flex items-center gap-2">
          <span
            className={cn("inline-block size-3 shrink-0 rounded-sm", swatch)}
            aria-hidden="true"
          />
          {label}
        </li>
      ))}
    </ul>
  );
}

/** No data in this window yet: a muted icon and a way forward. */
function EmptyState({
  icon,
  children,
}: {
  icon: LucideIcon;
  children: ReactNode;
}) {
  const Icon = icon;
  return (
    <div className="flex flex-col items-center gap-2 py-8 text-center">
      <Icon aria-hidden="true" className="size-8 text-muted-foreground/60" />
      <p className="max-w-prose text-sm text-pretty text-muted-foreground">
        {children}
      </p>
    </div>
  );
}

function ScoreDistribution({
  weeks,
  goodThreshold,
}: {
  weeks: readonly WeekInsights[];
  goodThreshold: number;
}) {
  const scores = totalScoreCounts(weeks);
  const total = scores.reduce((sum, { count }) => sum + count, 0);
  const max = Math.max(1, ...scores.map(({ count }) => count));
  const threshold = String(goodThreshold);
  return (
    <Panel
      id="scores-heading"
      title="Score distribution"
      description={`Ratings per whole score over ${weeks.length} weeks.`}
    >
      {total === 0 ? (
        <EmptyState icon={ChartNoAxesColumn}>
          No ratings in the last {weeks.length} weeks yet. Rate videos from your{" "}
          <Link
            to="/"
            className="underline underline-offset-2 hover:text-foreground"
          >
            feed
          </Link>{" "}
          and how your scores spread appears here.
        </EmptyState>
      ) : (
        <>
          <Legend
            items={[
              { label: `Good (${threshold} or higher)`, swatch: "bg-chart-1" },
              {
                label: `Below ${threshold}`,
                swatch: "bg-muted-foreground",
              },
            ]}
          />
          <ul className="flex flex-col gap-1" aria-label="Ratings per score">
            {scores.map(({ score, count }) => (
              <li
                key={score}
                title={`${count} of ${total} ratings (${formatPercent(count / total)})`}
                className="-mx-2 grid grid-cols-[2.75rem_minmax(0,1fr)_5rem] items-center gap-3 rounded-lg px-2 py-1 transition-colors duration-150 hover:bg-muted/50"
              >
                <span className="flex items-center justify-end gap-1.5 text-sm font-medium tabular-nums">
                  <ScoreFace
                    score={score}
                    filled
                    title={scoreLabel(score)}
                    className="size-4"
                  />
                  {score}
                </span>
                <span className="relative block h-4 w-full overflow-hidden rounded bg-muted">
                  {count > 0 && (
                    <span
                      aria-hidden="true"
                      className={cn(
                        "absolute inset-y-0 left-0 rounded",
                        isGoodBucket(score, goodThreshold)
                          ? "bg-chart-1"
                          : "bg-muted-foreground",
                      )}
                      style={{ width: `${(count / max) * 100}%` }}
                    />
                  )}
                </span>
                <span className="text-right text-sm tabular-nums">{count}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}

function ScoreShares({ weeks }: { weeks: readonly WeekInsights[] }) {
  const shown = weeks.filter((week) => week.score_share != null);
  return (
    <Panel
      id="shares-heading"
      title="Model vs subscriptions"
      description={
        shown.length === 0
          ? "Where the scores of each week's feed items came from."
          : "Where the scores of each week's feed items came from: the trained model, your channel preferences and tag subscriptions, or similarity to videos you rated."
      }
    >
      {shown.length === 0 ? (
        <EmptyState icon={ChartNoAxesColumn}>
          No feeds served in the last {weeks.length} weeks yet.{" "}
          <Link to="/">Open your feed</Link> to start them flowing.
        </EmptyState>
      ) : (
        <>
          <Legend items={SHARES} />
          <ul className="flex flex-col gap-1.5">
            {shown.map((week) => (
              <li
                key={week.week_start}
                className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-center gap-3"
              >
                <span className="text-sm text-muted-foreground tabular-nums">
                  {formatWeek(week.week_start)}
                </span>
                <ShareBar week={week} />
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}

function ShareBar({ week }: { week: WeekInsights }) {
  const share = week.score_share;
  if (!share) return null;
  const summary = SHARES.map(
    ({ key, label }) => `${label} ${formatPercent(share[key])}`,
  ).join(", ");
  return (
    <span
      role="img"
      aria-label={summary}
      title={summary}
      className="flex h-4 gap-0.5 overflow-hidden rounded"
    >
      {SHARES.map(({ key, label, swatch }) =>
        share[key] > 0 ? (
          <span
            key={key}
            title={`${label}: ${formatPercent(share[key])}`}
            className={cn("h-full", swatch)}
            style={{ width: `${share[key] * 100}%` }}
          />
        ) : null,
      )}
    </span>
  );
}

function WeekTable({
  weeks,
  currentWeek,
}: {
  weeks: readonly WeekInsights[];
  currentWeek?: WeekInsights;
}) {
  const [open, setOpen] = useState(false);
  const headingId = useId();
  const panelId = useId();
  const cell = "py-2 pr-4 text-right last:pr-0";
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle render={<h2 id={headingId} />} className="text-lg">
          Week by week
        </CardTitle>
        <Button
          variant="ghost"
          size="sm"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((value) => !value)}
        >
          <ChevronDown
            aria-hidden="true"
            data-icon="inline-start"
            className={cn(open && "rotate-180")}
          />
          {open ? "Hide" : "Show"}
          <span className="sr-only">the week-by-week table</span>
        </Button>
      </CardHeader>
      <CardContent id={panelId} hidden={!open}>
        <div className="max-h-96 overflow-auto">
          <table className="w-full text-sm tabular-nums">
            <thead className="text-muted-foreground">
              <tr>
                <th
                  scope="col"
                  className="sticky top-0 z-10 border-b bg-card py-2 pr-4 text-left font-medium"
                >
                  Week of
                </th>
                <th
                  scope="col"
                  className={cn(
                    cell,
                    "sticky top-0 z-10 border-b bg-card font-medium",
                  )}
                >
                  Good rate
                </th>
                <th
                  scope="col"
                  className={cn(
                    cell,
                    "sticky top-0 z-10 border-b bg-card font-medium",
                  )}
                >
                  Rating rate
                </th>
                {SHARES.map(({ key, label }) => (
                  <th
                    key={key}
                    scope="col"
                    className={cn(
                      cell,
                      "sticky top-0 z-10 border-b bg-card font-medium",
                    )}
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {[...weeks].reverse().map((week) => {
                const current = week.week_start === currentWeek?.week_start;
                return (
                  <tr
                    key={week.week_start}
                    className={cn(current && "bg-muted/40")}
                  >
                    <th
                      scope="row"
                      aria-current={current ? "date" : undefined}
                      className="py-2 pr-4 text-left font-normal whitespace-nowrap"
                    >
                      {formatWeek(week.week_start)}
                    </th>
                    <td className={cn(cell, "whitespace-nowrap")}>
                      {formatPercent(week.good_rate)}
                      {week.rated_count > 0 && (
                        <span className="text-muted-foreground">
                          {" "}
                          ({week.good_count}/{week.rated_count})
                        </span>
                      )}
                    </td>
                    <td className={cn(cell, "whitespace-nowrap")}>
                      {formatPercent(week.rating_rate)}
                      {week.shown_count > 0 && (
                        <span className="text-muted-foreground">
                          {" "}
                          ({week.shown_rated_count}/{week.shown_count})
                        </span>
                      )}
                    </td>
                    {SHARES.map(({ key }) => (
                      <td key={key} className={cell}>
                        {formatPercent(week.score_share?.[key])}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
      <CardFooter>
        <p className="max-w-prose text-sm text-pretty text-muted-foreground">
          Rating rate: of the videos shown in a week&apos;s feeds, how many you
          have rated. Shares split the size of each item&apos;s score terms;
          they add up to 100%.
        </p>
      </CardFooter>
    </Card>
  );
}

/** Skeleton placeholders that mirror the page while data is loading. */
function InsightsPending() {
  return (
    <AppShell className="flex max-w-5xl flex-col gap-10">
      <span className="sr-only">Loading insights…</span>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
        <div className="flex flex-col gap-2">
          <div className="h-5 w-24 rounded bg-muted motion-safe:animate-pulse" />
          <div className="h-4 w-72 rounded bg-muted motion-safe:animate-pulse" />
        </div>
        <div className="h-9 w-56 rounded-full bg-muted motion-safe:animate-pulse" />
      </div>
      <section className="flex flex-col gap-4">
        <div
          aria-hidden="true"
          className="h-6 w-32 rounded bg-muted motion-safe:animate-pulse"
        />
        <RecapSkeleton />
      </section>
      <div className="grid gap-3 sm:grid-cols-3" aria-hidden="true">
        {["good", "rating", "share"].map((key) => (
          <Card key={key} className="gap-3 p-5">
            <div className="flex flex-col gap-2">
              <div className="h-4 w-20 rounded bg-muted motion-safe:animate-pulse" />
              <div className="h-7 w-16 rounded bg-muted motion-safe:animate-pulse" />
              <div className="h-4 w-32 rounded bg-muted motion-safe:animate-pulse" />
            </div>
            <div className="h-5 w-full rounded bg-muted motion-safe:animate-pulse" />
          </Card>
        ))}
      </div>
      <Card aria-hidden="true" className="gap-4">
        <div className="flex flex-col gap-2 px-6">
          <div className="h-5 w-40 rounded bg-muted motion-safe:animate-pulse" />
          <div className="h-4 w-96 max-w-full rounded bg-muted motion-safe:animate-pulse" />
        </div>
        <div className="h-64 px-6">
          <div className="h-full w-full rounded bg-muted motion-safe:animate-pulse" />
        </div>
      </Card>
    </AppShell>
  );
}

function InsightsError() {
  const router = useRouter();
  const queryErrorResetBoundary = useQueryErrorResetBoundary();

  useEffect(() => {
    queryErrorResetBoundary.reset();
  }, [queryErrorResetBoundary]);

  return (
    <AppShell className="max-w-5xl">
      <div role="alert" className="mt-8 flex flex-col items-start gap-3">
        <p>Couldn&apos;t load insights. The API may be down.</p>
        <Button variant="secondary" onClick={() => void router.invalidate()}>
          Try again
        </Button>
      </div>
    </AppShell>
  );
}
