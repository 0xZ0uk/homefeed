import {
  listChannels,
  subscribeChannel,
  unsubscribeChannel,
  updateChannel,
  type ChannelPrefsInput,
  type SubscribedChannel,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for the curation page's channels tab. */

export type Prior = SubscribedChannel["prior"];
export const PRIORS: readonly Prior[] = [
  "love",
  "like",
  "neutral",
  "skeptical",
];

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
    return {
      channelId: data.channelId,
      prior: data.prior ?? undefined,
      pinned: typeof data.pinned === "boolean" ? data.pinned : undefined,
      muted: typeof data.muted === "boolean" ? data.muted : undefined,
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
