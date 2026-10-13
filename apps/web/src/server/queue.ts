import {
  addToQueue,
  clearQueue,
  listQueue,
  moveQueueItem,
  removeFromQueue,
  type QueueItem,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { isVideoId } from "#/lib/ids";
import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for the watch queue. */

export type { QueueItem };

export type EnqueueResult =
  | { ok: true; item: QueueItem; created: boolean }
  | { ok: false; message: string };

function checkId(id: unknown): number {
  if (!Number.isInteger(id)) throw new Error("id must be an integer");
  return id as number;
}

function checkPosition(position: unknown): number {
  if (!Number.isInteger(position) || (position as number) < 0) {
    throw new Error("position must be a non-negative integer");
  }
  return position as number;
}

const getQueue = createServerFn({ method: "GET" }).handler(async () => {
  const { data } = await listQueue({
    client: apiClient(),
    throwOnError: true,
  });
  return data;
});

export const queueQuery = queryOptions({
  queryKey: ["queue"],
  queryFn: () => getQueue(),
});

/** Queue a video, last unless `position` is given (0 is next up). */
export const enqueueVideo = createServerFn({ method: "POST" })
  .inputValidator((data: { videoId: string; position?: number }) => {
    if (typeof data.videoId !== "string" || !isVideoId(data.videoId)) {
      throw new Error("Not a video id");
    }
    return {
      videoId: data.videoId,
      position:
        data.position === undefined ? undefined : checkPosition(data.position),
    };
  })
  .handler(async ({ data }): Promise<EnqueueResult> => {
    const {
      data: item,
      error,
      response,
    } = await addToQueue({
      client: apiClient(),
      body: { video_id: data.videoId, position: data.position },
    });
    if (item) {
      return { ok: true, item, created: response?.status === 201 };
    }
    return {
      ok: false,
      message:
        response?.status === 404
          ? "That video doesn't exist or can't be watched."
          : apiErrorMessage(error, "Couldn't queue that. Try again later."),
    };
  });

/** Move an item; resolves to the whole queue in its new order. */
export const moveInQueue = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number; position: number }) => ({
    id: checkId(data.id),
    position: checkPosition(data.position),
  }))
  .handler(async ({ data }) => {
    const { data: items } = await moveQueueItem({
      client: apiClient(),
      path: { item_id: data.id },
      body: { position: data.position },
      throwOnError: true,
    });
    return items;
  });

export const dequeue = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number }) => ({ id: checkId(data.id) }))
  .handler(async ({ data }) => {
    const { response } = await removeFromQueue({
      client: apiClient(),
      path: { item_id: data.id },
    });
    // Already gone is fine.
    if (!response?.ok && response?.status !== 404) {
      throw new Error(
        `Couldn't remove that from the queue (${response?.status})`,
      );
    }
  });

export const emptyQueue = createServerFn({ method: "POST" }).handler(
  async () => {
    await clearQueue({ client: apiClient(), throwOnError: true });
  },
);
