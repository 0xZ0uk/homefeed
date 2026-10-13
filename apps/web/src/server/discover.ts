import {
  getChannelUploads,
  getSuggestedChannels,
  type ChannelUploadsOut,
  type SuggestedChannel,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { isChannelId } from "#/lib/discover";
import { apiClient } from "#/server/api";

/** Server functions for the discover page. Subscribing uses `channels.subscribe`. */

export type { ChannelUploadsOut, SuggestedChannel };

/** How many suggested channels the discover page shows. */
export const SUGGESTIONS_LIMIT = 20;
/** How many uploads a suggestion's preview lists. */
export const PREVIEW_UPLOADS = 5;

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

const fetchChannelUploads = createServerFn({ method: "GET" })
  .inputValidator((data: { channelId: string }) => {
    if (typeof data.channelId !== "string" || !isChannelId(data.channelId)) {
      throw new Error("channelId must be a YouTube channel id");
    }
    return { channelId: data.channelId };
  })
  .handler(async ({ data }): Promise<ChannelUploadsOut> => {
    const { data: uploads } = await getChannelUploads({
      client: apiClient(),
      path: { channel_id: data.channelId },
      query: { limit: PREVIEW_UPLOADS },
      throwOnError: true,
    });
    return uploads;
  });

export const channelUploadsQuery = (channelId: string) =>
  queryOptions({
    queryKey: ["channels", channelId, "uploads", PREVIEW_UPLOADS],
    queryFn: () => fetchChannelUploads({ data: { channelId } }),
    staleTime: 10 * 60 * 1000,
  });
