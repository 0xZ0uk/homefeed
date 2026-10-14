import {
  useQueryErrorResetBoundary,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useEffect, type ReactNode } from "react";

import { AppShell } from "#/components/AppShell";
import { GoodRateTrend } from "#/components/GoodRateTrend";
import { Button } from "#/components/ui/button";
import {
  formatPercent,
  formatWeek,
  isGoodBucket,
  overallGoodRate,
  overallRatingRate,
  plural,
  totalScoreCounts,
} from "#/lib/insights";
import { formatScore } from "#/lib/scores";
import { cn } from "#/lib/utils";
import {
  INSIGHTS_WEEKS,
  weeklyInsightsQuery,
  type WeekInsights,
} from "#/server/insights";

/** Whether the feed is working, by the success metric rather than watch time. */
export const Route = createFileRoute("/insights")({
  head: () => ({ meta: [{ title: "Insights · Homefeed" }] }),
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureQueryData(weeklyInsightsQuery),
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

function Insights() {
  const { data } = useSuspenseQuery(weeklyInsightsQuery);
  const weeks = data.weeks;
  const thisWeek = weeks.at(-1);

  return (
    <AppShell className="flex max-w-4xl flex-col gap-10">
      <header className="flex flex-col gap-1">
        <h2 className="text-xl font-semibold">Insights</h2>
        <p className="max-w-prose text-pretty text-muted-foreground">
          Is the feed working? The measure is the good rate: the share of rated
          videos scored {formatScore(data.good_threshold)} or higher. Last{" "}
          {INSIGHTS_WEEKS} weeks.
        </p>
      </header>

      {thisWeek && <ThisWeek week={thisWeek} />}

      <Section
        id="trend-heading"
        title="Good rate by week"
        description={`Over ${INSIGHTS_WEEKS} weeks: good rate ${formatPercent(
          overallGoodRate(weeks),
        )}, rating rate ${formatPercent(overallRatingRate(weeks))}.`}
      >
        <GoodRateTrend weeks={weeks} goodThreshold={data.good_threshold} />
      </Section>

      <ScoreDistribution weeks={weeks} goodThreshold={data.good_threshold} />
      <ScoreShares weeks={weeks} />
      <WeekTable weeks={weeks} />
    </AppShell>
  );
}

/** A titled part of the page, with an optional line under the title. */
function Section({
  id,
  title,
  description,
  children,
}: {
  id: string;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h3 id={id} className="text-lg font-semibold">
          {title}
        </h3>
        {description && (
          <p className="max-w-prose text-sm text-pretty text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      {children}
    </section>
  );
}

function ThisWeek({ week }: { week: WeekInsights }) {
  const stats = [
    {
      label: "Good rate",
      value: formatPercent(week.good_rate),
      detail:
        week.rated_count > 0
          ? `${week.good_count} of ${plural(week.rated_count, "rating")}`
          : "No ratings yet",
    },
    {
      label: "Rating rate",
      value: formatPercent(week.rating_rate),
      detail:
        week.shown_count > 0
          ? `${week.shown_rated_count} of ${plural(week.shown_count, "video")} shown`
          : "No feed yet",
    },
    {
      label: "Model share",
      value: formatPercent(week.score_share?.model),
      detail:
        week.feed_count > 0
          ? `${week.model_feed_count} of ${plural(week.feed_count, "feed")} used a model`
          : "No feed yet",
    },
  ];
  return (
    <Section
      id="this-week-heading"
      title={
        <>
          This week{" "}
          <span className="font-normal text-muted-foreground">
            (from {formatWeek(week.week_start)})
          </span>
        </>
      }
    >
      <dl className="grid gap-3 sm:grid-cols-3">
        {stats.map((stat) => (
          <div
            key={stat.label}
            className="flex flex-col gap-1 rounded-xl border p-4"
          >
            <dt className="text-sm font-medium text-muted-foreground">
              {stat.label}
            </dt>
            <dd className="text-3xl leading-tight font-semibold tracking-tight">
              {stat.value}
            </dd>
            <dd className="text-sm text-muted-foreground">{stat.detail}</dd>
          </div>
        ))}
      </dl>
    </Section>
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
  const threshold = formatScore(goodThreshold);
  return (
    <Section
      id="scores-heading"
      title="Score distribution"
      description={
        total > 0
          ? `${plural(total, "rating")} over ${INSIGHTS_WEEKS} weeks.`
          : `No ratings in the last ${INSIGHTS_WEEKS} weeks. Rate videos as you watch them to see how your scores spread.`
      }
    >
      {total > 0 && (
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
          <ul className="flex flex-col gap-1.5" aria-label="Ratings per score">
            {scores.map(({ score, count }) => (
              <li
                key={score}
                className="grid grid-cols-[1.5rem_minmax(0,1fr)] items-center gap-3"
              >
                <span className="text-right text-sm font-medium tabular-nums">
                  {score}
                </span>
                <span className="flex items-center gap-2">
                  {count > 0 && (
                    <span
                      aria-hidden="true"
                      className={cn(
                        "block h-4 shrink-0 rounded-r",
                        isGoodBucket(score, goodThreshold)
                          ? "bg-chart-1"
                          : "bg-muted-foreground",
                      )}
                      style={{
                        width: `calc((100% - 6rem) * ${count / max})`,
                      }}
                    />
                  )}
                  <span className="text-sm whitespace-nowrap tabular-nums">
                    {count}{" "}
                    <span className="text-muted-foreground">
                      ({formatPercent(count / total)})
                    </span>
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Section>
  );
}

function ScoreShares({ weeks }: { weeks: readonly WeekInsights[] }) {
  const shown = weeks.filter((week) => week.score_share != null);
  return (
    <Section
      id="shares-heading"
      title="Model vs subscriptions"
      description={
        shown.length === 0
          ? `Where the scores of each week's feed items came from. No feeds in the last ${INSIGHTS_WEEKS} weeks.`
          : "Where the scores of each week's feed items came from: the trained model, your channel priors and tag subscriptions, or similarity to videos you rated."
      }
    >
      {shown.length > 0 && (
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
    </Section>
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
      {SHARES.map(({ key, swatch }) =>
        share[key] > 0 ? (
          <span
            key={key}
            className={cn("h-full", swatch)}
            style={{ width: `${share[key] * 100}%` }}
          />
        ) : null,
      )}
    </span>
  );
}

function WeekTable({ weeks }: { weeks: readonly WeekInsights[] }) {
  const cell = "py-2 pr-4 text-right last:pr-0";
  return (
    <details className="flex flex-col">
      <summary className="-mx-2 w-fit cursor-pointer rounded-lg px-2 py-1 text-lg font-semibold hover:bg-secondary">
        Week by week
      </summary>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm tabular-nums">
          <thead className="border-b text-muted-foreground">
            <tr>
              <th scope="col" className="py-2 pr-4 text-left font-medium">
                Week of
              </th>
              <th scope="col" className={cn(cell, "font-medium")}>
                Good rate
              </th>
              <th scope="col" className={cn(cell, "font-medium")}>
                Rating rate
              </th>
              {SHARES.map(({ key, label }) => (
                <th key={key} scope="col" className={cn(cell, "font-medium")}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y">
            {[...weeks].reverse().map((week) => (
              <tr key={week.week_start}>
                <th
                  scope="row"
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
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 max-w-prose text-sm text-pretty text-muted-foreground">
        Rating rate: of the videos shown in a week&apos;s feeds, how many you
        have rated. Shares split the size of each item&apos;s score terms; they
        add up to 100%.
      </p>
    </details>
  );
}

function InsightsError() {
  const router = useRouter();
  const queryErrorResetBoundary = useQueryErrorResetBoundary();

  useEffect(() => {
    queryErrorResetBoundary.reset();
  }, [queryErrorResetBoundary]);

  return (
    <AppShell className="max-w-4xl">
      <div role="alert" className="mt-8 flex flex-col items-start gap-3">
        <p>Couldn&apos;t load insights. The API may be down.</p>
        <Button variant="secondary" onClick={() => void router.invalidate()}>
          Try again
        </Button>
      </div>
    </AppShell>
  );
}
