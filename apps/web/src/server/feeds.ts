import {
  dismissFeedItem,
  extendFeed,
  getFeed,
  getTodayFeed,
  refreshFeed,
  type FeedOut,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { isFeedDate } from "#/lib/format";
import { apiClient } from "#/server/api";

/** Server functions for the home feed. */

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

/** Dismiss a feed item, with an optional reason (blank means none). */
export const dismissItem = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number; reason?: string | null }) => {
    if (!Number.isInteger(data.id) || data.id < 1) {
      throw new Error("id must be a positive integer");
    }
    if (data.reason != null && typeof data.reason !== "string") {
      throw new Error("reason must be a string");
    }
    return { id: data.id, reason: data.reason?.trim() || null };
  })
  .handler(async ({ data }): Promise<FeedItem> => {
    const { data: item } = await dismissFeedItem({
      client: apiClient(),
      path: { item_id: data.id },
      body: { reason: data.reason },
      throwOnError: true,
    });
    return item;
  });

/** Append the next page of ranked picks to a stored feed. */
export const loadMoreFeed = createServerFn({ method: "POST" })
  .inputValidator((data: { feedId: number }) => {
    if (!Number.isInteger(data.feedId) || data.feedId < 1) {
      throw new Error("feedId must be a positive integer");
    }
    return { feedId: data.feedId };
  })
  .handler(async ({ data }): Promise<Feed> => {
    const { data: feed } = await extendFeed({
      client: apiClient(),
      path: { feed_id: data.feedId },
      throwOnError: true,
    });
    return feed;
  });

export const todayFeedQuery = queryOptions({
  queryKey: ["feed", "today"],
  queryFn: () => fetchTodayFeed(),
});

export const feedQuery = (date: string) =>
  queryOptions({
    queryKey: ["feed", date],
    queryFn: () => fetchFeed({ data: { date } }),
  });
