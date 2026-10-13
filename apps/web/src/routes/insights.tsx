import {
  useQueryErrorResetBoundary,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useEffect } from "react";

import { AppShell } from "#/components/AppShell";
import { GoodTierTrend } from "#/components/GoodTierTrend";
import {
  formatPercent,
  formatWeek,
  overallGoodTierRate,
  overallRatingRate,
  plural,
  totalTierCounts,
} from "#/lib/insights";
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

// Categorical slots 1–3 of the chart palette, in a fixed order.
const SHARES = [
  { key: "model", label: "Model", color: "#2a78d6" },
  { key: "curation", label: "Curation (channels, topics)", color: "#eb6834" },
  { key: "similarity", label: "Similarity to ratings", color: "#1baf7a" },
] as const;

function Insights() {
  const { data } = useSuspenseQuery(weeklyInsightsQuery);
  const weeks = data.weeks;
  const thisWeek = weeks.at(-1);

  return (
    <AppShell className="flex max-w-4xl flex-col gap-8">
      <div className="flex flex-col gap-1">
        <h2 className="text-xl font-semibold">Insights</h2>
        <p className="text-muted-foreground">
          Is the feed working? The measure is the good-tier rate: the share of
          rated videos rated {data.good_threshold} or higher. Last{" "}
          {INSIGHTS_WEEKS} weeks.
        </p>
      </div>

      {thisWeek && <ThisWeek week={thisWeek} />}

      <section aria-labelledby="trend-heading" className="flex flex-col gap-3">
        <h3 id="trend-heading" className="text-lg font-semibold">
          Good-tier rate by week
        </h3>
        <p className="text-sm text-muted-foreground">
          Over {INSIGHTS_WEEKS} weeks: good-tier rate{" "}
          {formatPercent(overallGoodTierRate(weeks))}, rating rate{" "}
          {formatPercent(overallRatingRate(weeks))}.
        </p>
        <GoodTierTrend weeks={weeks} />
      </section>

      <TierDistribution weeks={weeks} />
      <ScoreShares weeks={weeks} />
      <WeekTable weeks={weeks} />
    </AppShell>
  );
}

function ThisWeek({ week }: { week: WeekInsights }) {
  const stats = [
    {
      label: "Good-tier rate",
      value: formatPercent(week.good_tier_rate),
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
    <section
      aria-labelledby="this-week-heading"
      className="flex flex-col gap-3"
    >
      <h3 id="this-week-heading" className="text-lg font-semibold">
        This week{" "}
        <span className="font-normal text-muted-foreground">
          (from {formatWeek(week.week_start)})
        </span>
      </h3>
      <dl className="grid gap-4 sm:grid-cols-3">
        {stats.map((stat) => (
          <div
            key={stat.label}
            className="flex flex-col rounded-xl border border-border p-4"
          >
            <dt className="text-sm text-muted-foreground">{stat.label}</dt>
            <dd className="text-3xl font-semibold tabular-nums">
              {stat.value}
            </dd>
            <dd className="text-sm text-muted-foreground">{stat.detail}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function TierDistribution({ weeks }: { weeks: readonly WeekInsights[] }) {
  const tiers = totalTierCounts(weeks);
  const total = tiers.reduce((sum, { count }) => sum + count, 0);
  const max = Math.max(1, ...tiers.map(({ count }) => count));
  return (
    <section aria-labelledby="tiers-heading" className="flex flex-col gap-3">
      <h3 id="tiers-heading" className="text-lg font-semibold">
        Tier distribution
      </h3>
      <p className="text-sm text-muted-foreground">
        {total > 0
          ? `${plural(total, "rating")} over ${INSIGHTS_WEEKS} weeks.`
          : `No ratings in the last ${INSIGHTS_WEEKS} weeks.`}
      </p>
      {total > 0 && (
        <ul className="flex flex-col gap-1">
          {tiers.map(({ tier, count }) => (
            <li
              key={tier}
              className="grid grid-cols-[1.5rem_1fr_5rem] items-center gap-3"
            >
              <span className="font-semibold">{tier}</span>
              <span className="h-4" aria-hidden="true">
                {count > 0 && (
                  <span
                    className="block h-full rounded-r bg-[#2a78d6]"
                    style={{ width: `${(count / max) * 100}%` }}
                  />
                )}
              </span>
              <span className="text-sm tabular-nums">
                {count}{" "}
                <span className="text-muted-foreground">
                  ({formatPercent(count / total)})
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ScoreShares({ weeks }: { weeks: readonly WeekInsights[] }) {
  const shown = weeks.filter((week) => week.score_share != null);
  return (
    <section aria-labelledby="shares-heading" className="flex flex-col gap-3">
      <h3 id="shares-heading" className="text-lg font-semibold">
        Model vs curation
      </h3>
      <p className="text-sm text-muted-foreground">
        Where the scores of each week's feed items came from: the trained model,
        your channel priors and topics, or similarity to videos you rated.
      </p>
      {shown.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No feeds in the last {INSIGHTS_WEEKS} weeks.
        </p>
      ) : (
        <>
          <ul className="flex flex-wrap gap-4 text-sm">
            {SHARES.map(({ key, label, color }) => (
              <li key={key} className="flex items-center gap-2">
                <span
                  className="inline-block size-3 rounded-sm"
                  style={{ backgroundColor: color }}
                  aria-hidden="true"
                />
                {label}
              </li>
            ))}
          </ul>
          <ul className="flex flex-col gap-1">
            {shown.map((week) => (
              <li
                key={week.week_start}
                className="grid grid-cols-[4rem_1fr] items-center gap-3"
              >
                <span className="text-sm">{formatWeek(week.week_start)}</span>
                <ShareBar week={week} />
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
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
      {SHARES.map(({ key, color }) =>
        share[key] > 0 ? (
          <span
            key={key}
            className="h-full"
            style={{ width: `${share[key] * 100}%`, backgroundColor: color }}
          />
        ) : null,
      )}
    </span>
  );
}

function WeekTable({ weeks }: { weeks: readonly WeekInsights[] }) {
  return (
    <details>
      <summary className="cursor-pointer text-lg font-semibold">
        Week by week
      </summary>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-sm tabular-nums">
          <thead className="text-muted-foreground">
            <tr>
              <th scope="col" className="py-1 pr-3 font-medium">
                Week of
              </th>
              <th scope="col" className="py-1 pr-3 font-medium">
                Good-tier rate
              </th>
              <th scope="col" className="py-1 pr-3 font-medium">
                Rating rate
              </th>
              {SHARES.map(({ key, label }) => (
                <th key={key} scope="col" className="py-1 pr-3 font-medium">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...weeks].reverse().map((week) => (
              <tr key={week.week_start} className="border-t border-border">
                <th scope="row" className="py-1 pr-3 font-normal">
                  {formatWeek(week.week_start)}
                </th>
                <td className="py-1 pr-3">
                  {formatPercent(week.good_tier_rate)}
                  {week.rated_count > 0 && (
                    <span className="text-muted-foreground">
                      {" "}
                      ({week.good_count}/{week.rated_count})
                    </span>
                  )}
                </td>
                <td className="py-1 pr-3">
                  {formatPercent(week.rating_rate)}
                  {week.shown_count > 0 && (
                    <span className="text-muted-foreground">
                      {" "}
                      ({week.shown_rated_count}/{week.shown_count})
                    </span>
                  )}
                </td>
                {SHARES.map(({ key }) => (
                  <td key={key} className="py-1 pr-3">
                    {formatPercent(week.score_share?.[key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-sm text-muted-foreground">
        Rating rate: of the videos shown in a week's feeds, how many you have
        rated. Shares split the size of each item's score terms; they add up to
        100%.
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
        <p>Couldn't load insights. The API may be down.</p>
        <button
          type="button"
          onClick={() => void router.invalidate()}
          className="underline"
        >
          Try again
        </button>
      </div>
    </AppShell>
  );
}
