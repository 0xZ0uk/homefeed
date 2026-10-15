import {
  endChannelTrial,
  keepChannelTrial,
  listChannelHealth,
  listChannels,
  startChannelTrial,
  subscribeChannel,
  unsubscribeChannel,
  updateChannel,
  type ChannelPrefsInput,
  type SubscribedChannel,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { PICKS_WINDOW_DAYS } from "#/lib/channel-health";
import { PRIORS } from "#/lib/channels";
import { isChannelId } from "#/lib/discover";
import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for the Subscriptions page's channels tab. */

export type SubscribeResult =
  | { ok: true; channel: SubscribedChannel; created: boolean }
  | { ok: false; message: string };

export interface ChannelPrefsUpdate extends ChannelPrefsInput {
  channelId: string;
}

const getChannels = createServerFn({ method: "GET" }).handler(async () => {
  const { data } = await listChannels({
    client: apiClient(),
    throwOnError: true,
  });
  return data;
});

export const channelsQuery = queryOptions({
  queryKey: ["channels"],
  queryFn: () => getChannels(),
});

const getChannelHealth = createServerFn({ method: "GET" }).handler(async () => {
  const { data } = await listChannelHealth({
    client: apiClient(),
    query: { days: PICKS_WINDOW_DAYS },
    throwOnError: true,
  });
  return data;
});

/**
 * Per channel: picks lately, how many were watched, ratings and when it was
 * last watched. Under the channels' key, so whatever refreshes the channels
 * refreshes these too.
 */
export const channelHealthQuery = queryOptions({
  queryKey: ["channels", "health"],
  queryFn: () => getChannelHealth(),
});

export const subscribe = createServerFn({ method: "POST" })
  .inputValidator((data: { url: string }) => {
    if (typeof data.url !== "string") throw new Error("url must be a string");
    return { url: data.url.trim() };
  })
  .handler(async ({ data }): Promise<SubscribeResult> => {
    const {
      data: channel,
      error,
      response,
    } = await subscribeChannel({
      client: apiClient(),
      body: { url: data.url },
    });
    if (channel) {
      return { ok: true, channel, created: response?.status === 201 };
    }
    return {
      ok: false,
      message: apiErrorMessage(
        error,
        response?.status === 422
          ? "That doesn't look like a YouTube channel link."
          : "Couldn't subscribe. Try again later.",
      ),
    };
  });

export const updatePrefs = createServerFn({ method: "POST" })
  .inputValidator((data: ChannelPrefsUpdate) => {
    if (typeof data.channelId !== "string") {
      throw new Error("channelId must be a string");
    }
    if (data.prior != null && !PRIORS.includes(data.prior)) {
      throw new Error(`Unknown prior ${String(data.prior)}`);
    }
    if (
      data.mute_days != null &&
      (!Number.isInteger(data.mute_days) || data.mute_days < 1)
    ) {
      throw new Error("mute_days must be a whole number of days");
    }
    return {
      channelId: data.channelId,
      prior: data.prior ?? undefined,
      pinned: typeof data.pinned === "boolean" ? data.pinned : undefined,
      muted: typeof data.muted === "boolean" ? data.muted : undefined,
      mute_days: data.mute_days ?? undefined,
    };
  })
  .handler(async ({ data: { channelId, ...body } }) => {
    const { data } = await updateChannel({
      client: apiClient(),
      path: { channel_id: channelId },
      body,
      throwOnError: true,
    });
    return data;
  });

export const unsubscribe = createServerFn({ method: "POST" })
  .inputValidator((data: { channelId: string }) => {
    if (typeof data.channelId !== "string") {
      throw new Error("channelId must be a string");
    }
    return { channelId: data.channelId };
  })
  .handler(async ({ data }) => {
    await unsubscribeChannel({
      client: apiClient(),
      path: { channel_id: data.channelId },
      throwOnError: true,
    });
  });

function channelIdOf(data: { channelId: string }): { channelId: string } {
  if (typeof data.channelId !== "string" || !isChannelId(data.channelId)) {
    throw new Error("channelId must be a YouTube channel id");
  }
  return { channelId: data.channelId };
}

/**
 * Subscribe to a channel you already know of (a suggestion) on a trial of two
 * weeks. `created` is false if you were subscribed already, trial or not.
 */
export const startTrial = createServerFn({ method: "POST" })
  .inputValidator(channelIdOf)
  .handler(async ({ data }) => {
    const { data: channel, response } = await startChannelTrial({
      client: apiClient(),
      path: { channel_id: data.channelId },
      throwOnError: true,
    });
    return { channel, created: response.status === 201 };
  });

/** Make a trial a plain subscription. */
export const keepTrial = createServerFn({ method: "POST" })
  .inputValidator(channelIdOf)
  .handler(async ({ data }) => {
    const { data: channel } = await keepChannelTrial({
      client: apiClient(),
      path: { channel_id: data.channelId },
      throwOnError: true,
    });
    return channel;
  });

/** End a trial now: unsubscribe, and don't suggest the channel again. */
export const endTrial = createServerFn({ method: "POST" })
  .inputValidator(channelIdOf)
  .handler(async ({ data }) => {
    await endChannelTrial({
      client: apiClient(),
      path: { channel_id: data.channelId },
      throwOnError: true,
    });
  });
