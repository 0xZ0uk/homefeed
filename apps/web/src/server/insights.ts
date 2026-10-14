import {
  getWeeklyInsights,
  type WeeklyInsightsOut,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { apiClient } from "#/server/api";

/** Server functions for the insights page. */

export type WeeklyInsights = WeeklyInsightsOut;
export type WeekInsights = WeeklyInsightsOut["weeks"][number];

/** How many weeks the insights page shows by default, ending with this week. */
export const INSIGHTS_WEEKS = 12;

const fetchWeeklyInsights = createServerFn({ method: "GET" })
  .inputValidator((data: { weeks: number }) => {
    const weeks = Math.round(data?.weeks ?? INSIGHTS_WEEKS);
    if (!Number.isInteger(weeks) || weeks < 1 || weeks > 104) {
      throw new Error("weeks must be between 1 and 104");
    }
    return weeks;
  })
  .handler(async ({ data: weeks }): Promise<WeeklyInsights> => {
    const { data } = await getWeeklyInsights({
      client: apiClient(),
      query: { weeks },
      throwOnError: true,
    });
    return data;
  });

function weeklyInsightsOptions(weeks: number) {
  return queryOptions({
    queryKey: ["insights", "weekly", weeks],
    queryFn: () => fetchWeeklyInsights({ data: { weeks } }),
  });
}

/**
 * Weekly insights for the last `weeks` weeks, ending with this one. Call it
 * with a span (`weeklyInsightsQuery(26)`) or use it directly for the default
 * `INSIGHTS_WEEKS`:
 *
 *     useSuspenseQuery(weeklyInsightsQuery(weeks))
 *     queryClient.ensureQueryData(weeklyInsightsQuery)
 */
export const weeklyInsightsQuery = Object.assign(
  (weeks: number = INSIGHTS_WEEKS) => weeklyInsightsOptions(weeks),
  weeklyInsightsOptions(INSIGHTS_WEEKS),
);
export type WeeklyInsightsQuery = ReturnType<typeof weeklyInsightsQuery>;
