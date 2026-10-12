import {
  getFeed,
  getTodayFeed,
  listFeeds,
  refreshFeed,
  type FeedOut,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { isFeedDate } from "#/lib/format";
import { apiClient } from "#/server/api";

/** Server functions for the home feed and feed history. */

export type Feed = FeedOut;
export type FeedItem = FeedOut["items"][number];

/** Today's feed, or null when none has been built yet. */
const fetchTodayFeed = createServerFn({ method: "GET" }).handler(
  async (): Promise<Feed | null> => {
    const { data, response } = await getTodayFeed({ client: apiClient() });
    if (data) return data;
    if (response?.status === 404) return null;
    throw new Error(`Couldn't load today's feed (${response?.status})`);
  },
);

/** The feed for a date, or null when none was built that day. */
const fetchFeed = createServerFn({ method: "GET" })
  .inputValidator((data: { date: string }) => {
    if (!isFeedDate(data.date)) throw new Error("date must be YYYY-MM-DD");
    return { date: data.date };
  })
  .handler(async ({ data }): Promise<Feed | null> => {
    const { data: feed, response } = await getFeed({
      client: apiClient(),
      path: { feed_date: data.date },
    });
    if (feed) return feed;
    if (response?.status === 404) return null;
    throw new Error(
      `Couldn't load the feed for ${data.date} (${response?.status})`,
    );
  });

const fetchFeedHistory = createServerFn({ method: "GET" }).handler(async () => {
  const { data } = await listFeeds({ client: apiClient(), throwOnError: true });
  return data;
});

/** Poll subscriptions and build a new feed for today. */
export const rebuildFeed = createServerFn({ method: "POST" }).handler(
  async (): Promise<Feed> => {
    const { data } = await refreshFeed({
      client: apiClient(),
      throwOnError: true,
    });
    return data;
  },
);

export const todayFeedQuery = queryOptions({
  queryKey: ["feed", "today"],
  queryFn: () => fetchTodayFeed(),
});

export const feedQuery = (date: string) =>
  queryOptions({
    queryKey: ["feed", date],
    queryFn: () => fetchFeed({ data: { date } }),
  });

export const feedHistoryQuery = queryOptions({
  queryKey: ["feeds"],
  queryFn: () => fetchFeedHistory(),
});
