import {
  hideChannel,
  listChannelHides,
  unhideChannel,
  type ChannelHide,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { isChannelId } from "#/lib/discover";
import { apiClient } from "#/server/api";

/** Server functions for hiding channels from Discover or the feed. */

export type { ChannelHide };
export type HideKind = ChannelHide["kind"];

function channelIdOf(data: { channelId: string }): string {
  if (typeof data.channelId !== "string" || !isChannelId(data.channelId)) {
    throw new Error("channelId must be a YouTube channel id");
  }
  return data.channelId;
}

const fetchChannelHides = createServerFn({ method: "GET" }).handler(
  async (): Promise<ChannelHide[]> => {
    const { data } = await listChannelHides({
      client: apiClient(),
      throwOnError: true,
    });
    return data;
  },
);

export const channelHidesQuery = queryOptions({
  queryKey: ["channel-hides"],
  queryFn: () => fetchChannelHides(),
});

export const hide = createServerFn({ method: "POST" })
  .inputValidator((data: { channelId: string; kind: HideKind }) => {
    if (data.kind !== "dismissed" && data.kind !== "blocked") {
      throw new Error("kind must be dismissed or blocked");
    }
    return { channelId: channelIdOf(data), kind: data.kind };
  })
  .handler(async ({ data }): Promise<ChannelHide> => {
    const { data: hidden } = await hideChannel({
      client: apiClient(),
      path: { channel_id: data.channelId },
      body: { kind: data.kind },
      throwOnError: true,
    });
    return hidden;
  });

export const unhide = createServerFn({ method: "POST" })
  .inputValidator((data: { channelId: string }) => ({
    channelId: channelIdOf(data),
  }))
  .handler(async ({ data }) => {
    await unhideChannel({
      client: apiClient(),
      path: { channel_id: data.channelId },
      throwOnError: true,
    });
  });
