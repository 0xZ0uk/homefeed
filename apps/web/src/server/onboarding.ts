import {
  completeOnboarding,
  getOnboarding,
  refreshFeed,
  searchVideos,
  type OnboardingOut,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { channelHits, type ChannelHit } from "#/lib/onboarding";
import { QUERY_MAX_LENGTH } from "#/lib/search";
import { apiClient, apiErrorMessage } from "#/server/api";
import type { Feed } from "#/server/feeds";

/** Server functions for the first-run setup. */

export type Onboarding = OnboardingOut;

export type ChannelSearchOutcome =
  { ok: true; channels: ChannelHit[] } | { ok: false; message: string };

const fetchOnboarding = createServerFn({ method: "GET" }).handler(
  async (): Promise<Onboarding> => {
    const { data } = await getOnboarding({
      client: apiClient(),
      throwOnError: true,
    });
    return data;
  },
);

/** Whether setup is due. Never stale: it flips when a channel is subscribed. */
export const onboardingQuery = queryOptions({
  queryKey: ["onboarding"],
  queryFn: () => fetchOnboarding(),
  staleTime: 0,
});

/** Mark setup done without building a feed. */
export const skipOnboarding = createServerFn({ method: "POST" }).handler(
  async (): Promise<Onboarding> => {
    const { data } = await completeOnboarding({
      client: apiClient(),
      throwOnError: true,
    });
    return data;
  },
);

/**
 * Build the first feed, then mark setup done. The refresh polls every
 * subscription that was never polled, so the new channels' latest uploads are
 * candidates by the time the feed is composed. Setup stays open if it fails.
 */
export const finishOnboarding = createServerFn({ method: "POST" }).handler(
  async (): Promise<Feed> => {
    const { data: feed } = await refreshFeed({
      client: apiClient(),
      throwOnError: true,
    });
    await completeOnboarding({ client: apiClient(), throwOnError: true });
    return feed;
  },
);

/** Channels found by searching YouTube for `q`, by way of their videos. */
export const searchChannels = createServerFn({ method: "POST" })
  .inputValidator((data: { q: string }) => {
    const q = typeof data.q === "string" ? data.q.trim() : "";
    if (!q || q.length > QUERY_MAX_LENGTH) {
      throw new Error("q must be a non-blank string");
    }
    return { q };
  })
  .handler(async ({ data }): Promise<ChannelSearchOutcome> => {
    const {
      data: results,
      error,
      response,
    } = await searchVideos({ client: apiClient(), query: { q: data.q } });
    if (results) return { ok: true, channels: channelHits(results) };
    return {
      ok: false,
      message:
        response?.status === 502
          ? "YouTube couldn't be reached. Try again in a few minutes."
          : apiErrorMessage(error, "Couldn't search right now. Try again later."),
    };
  });
