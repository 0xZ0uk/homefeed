import {
  getChannelProfile,
  getDiscoveryVideos,
  getSuggestedChannels,
  refreshSuggestedChannels,
  type ChannelProfileOut,
  type DiscoveryItemOut,
  type SuggestedChannel,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { isChannelId } from "#/lib/discover";
import { apiClient, apiErrorMessage } from "#/server/api";

/**
 * Server functions for the discover page and the home page's Discovery
 * carousel. Subscribing uses `channels.subscribe`.
 */

export type { ChannelProfileOut, SuggestedChannel };
export type DiscoveryVideo = DiscoveryItemOut;

/** How many videos the home page's Discovery carousel shows. */
export const DISCOVERY_LIMIT = 10;

/** How many suggested channels the discover page shows. */
export const SUGGESTIONS_LIMIT = 20;
/** How many uploads a channel page lists. */
export const PROFILE_UPLOADS = 12;

const fetchSuggestedChannels = createServerFn({ method: "GET" }).handler(
  async (): Promise<SuggestedChannel[]> => {
    const { data } = await getSuggestedChannels({
      client: apiClient(),
      query: { limit: SUGGESTIONS_LIMIT },
      throwOnError: true,
    });
    return data;
  },
);

export const suggestedChannelsQuery = queryOptions({
  queryKey: ["discover", "suggested-channels", SUGGESTIONS_LIMIT],
  queryFn: () => fetchSuggestedChannels(),
});

const fetchDiscoveryVideos = createServerFn({ method: "GET" }).handler(
  async (): Promise<DiscoveryVideo[]> => {
    const { data } = await getDiscoveryVideos({
      client: apiClient(),
      query: { limit: DISCOVERY_LIMIT },
      throwOnError: true,
    });
    return data;
  },
);

/**
 * The best picks from outside the subscriptions, leaving out today's feed.
 * Ranking them takes a moment, so they're kept for a while; refreshing the
 * feed invalidates them, since what's in it changes.
 */
export const discoveryVideosQuery = queryOptions({
  queryKey: ["discover", "videos", DISCOVERY_LIMIT],
  queryFn: () => fetchDiscoveryVideos(),
  staleTime: 5 * 60 * 1000,
});

/** Re-crawl the featured channels, preferring ones not in `exclude`. */
export const refreshSuggestions = createServerFn({ method: "POST" })
  .inputValidator((data: { exclude: string[] }) => {
    if (!Array.isArray(data.exclude)) throw new Error("exclude must be a list");
    return { exclude: data.exclude.filter(isChannelId) };
  })
  .handler(async ({ data }): Promise<SuggestedChannel[]> => {
    const { data: channels } = await refreshSuggestedChannels({
      client: apiClient(),
      query: { limit: SUGGESTIONS_LIMIT, exclude: data.exclude },
      throwOnError: true,
    });
    return channels;
  });

/** A channel's profile and latest uploads, or null when there's no such channel. */
const fetchChannelProfile = createServerFn({ method: "GET" })
  .inputValidator((data: { channelId: string }) => {
    if (typeof data.channelId !== "string" || !isChannelId(data.channelId)) {
      throw new Error("channelId must be a YouTube channel id");
    }
    return { channelId: data.channelId };
  })
  .handler(async ({ data }): Promise<ChannelProfileOut | null> => {
    const {
      data: profile,
      error,
      response,
    } = await getChannelProfile({
      client: apiClient(),
      path: { channel_id: data.channelId },
      query: { limit: PROFILE_UPLOADS },
    });
    if (profile) return profile;
    if (response?.status === 404) return null;
    throw new Error(
      apiErrorMessage(error, `Couldn't load the channel (${response?.status})`),
    );
  });

export const channelProfileQuery = (channelId: string) =>
  queryOptions({
    queryKey: ["channels", channelId, "profile"],
    queryFn: () => fetchChannelProfile({ data: { channelId } }),
    staleTime: 5 * 60 * 1000,
  });
