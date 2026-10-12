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

/** How many weeks the insights page shows, ending with this week. */
export const INSIGHTS_WEEKS = 12;

const fetchWeeklyInsights = createServerFn({ method: "GET" }).handler(
  async (): Promise<WeeklyInsights> => {
    const { data } = await getWeeklyInsights({
      client: apiClient(),
      query: { weeks: INSIGHTS_WEEKS },
      throwOnError: true,
    });
    return data;
  },
);

export const weeklyInsightsQuery = queryOptions({
  queryKey: ["insights", "weekly", INSIGHTS_WEEKS],
  queryFn: () => fetchWeeklyInsights(),
});
