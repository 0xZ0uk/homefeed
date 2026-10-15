import {
  clearVideoFeedback,
  dismissFeedItem,
  extendFeed,
  getFeed,
  getTodayFeed,
  getWildcards,
  listFeeds,
  refreshFeed,
  setVideoFeedback,
  undismissFeedItem,
  type DiscoveryItemOut,
  type FeedOut,
  type FeedSummaryOut,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { isSignal, type Signal } from "#/lib/feedback";
import { isFeedDate } from "#/lib/format";
import { isVideoId } from "#/lib/ids";
import { apiClient } from "#/server/api";

/** Server functions for the home feed. */

export type Feed = FeedOut;
export type FeedItem = FeedOut["items"][number];
export type FeedSummary = FeedSummaryOut;
/** A video from outside the topics I follow: a card of its own, not a feed item. */
export type Wildcard = DiscoveryItemOut;

/** How many videos "Show 3 wildcards" shows. */
export const WILDCARDS_LIMIT = 3;
/** How many of the latest feeds to look through for one with leftovers. */
export const FEED_HISTORY = 7;

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

/** The latest feed of each of the last few days, newest first. */
const fetchFeedList = createServerFn({ method: "GET" }).handler(
  async (): Promise<FeedSummary[]> => {
    const { data } = await listFeeds({
      client: apiClient(),
      query: { limit: FEED_HISTORY },
      throwOnError: true,
    });
    return data;
  },
);

/** A few videos on topics I don't follow, the same all day. */
const fetchWildcards = createServerFn({ method: "GET" }).handler(
  async (): Promise<Wildcard[]> => {
    const { data } = await getWildcards({
      client: apiClient(),
      query: { limit: WILDCARDS_LIMIT },
      throwOnError: true,
    });
    return data;
  },
);

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

/** Take back the dismissal of a feed item. */
export const undismissItem = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number }) => {
    if (!Number.isInteger(data.id) || data.id < 1) {
      throw new Error("id must be a positive integer");
    }
    return { id: data.id };
  })
  .handler(async ({ data }): Promise<FeedItem> => {
    const { data: item } = await undismissFeedItem({
      client: apiClient(),
      path: { item_id: data.id },
      throwOnError: true,
    });
    return item;
  });

/**
 * Mark a video "more like this" (1) or "less like this" (-1), or take its
 * feedback off with null.
 */
export const saveFeedback = createServerFn({ method: "POST" })
  .inputValidator((data: { videoId: string; signal: Signal | null }) => {
    if (typeof data.videoId !== "string" || !isVideoId(data.videoId)) {
      throw new Error("Not a video id");
    }
    if (data.signal !== null && !isSignal(data.signal)) {
      throw new Error("signal must be 1, -1 or null");
    }
    return { videoId: data.videoId, signal: data.signal };
  })
  .handler(async ({ data }): Promise<void> => {
    if (data.signal === null) {
      const { response } = await clearVideoFeedback({
        client: apiClient(),
        path: { video_id: data.videoId },
      });
      // Already gone is fine.
      if (!response?.ok && response?.status !== 404) {
        throw new Error(`Couldn't clear the feedback (${response?.status})`);
      }
      return;
    }
    await setVideoFeedback({
      client: apiClient(),
      path: { video_id: data.videoId },
      body: { signal: data.signal },
      throwOnError: true,
    });
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

/** The days that have a feed, to find the last one when today has none yet. */
export const feedListQuery = queryOptions({
  queryKey: ["feeds"],
  queryFn: () => fetchFeedList(),
});

/**
 * The wildcards for the end of the feed. They are the same all day, so they
 * are kept for a while; building a new feed invalidates them, since what's in
 * it changes.
 */
export const wildcardsQuery = queryOptions({
  queryKey: ["wildcards", WILDCARDS_LIMIT],
  queryFn: () => fetchWildcards(),
  staleTime: 5 * 60 * 1000,
});
