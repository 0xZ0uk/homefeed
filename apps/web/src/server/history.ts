import {
  getHistoryEntry,
  getHistorySummary,
  searchHistory,
  type HistoryEntry,
  type HistorySummary,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import {
  HISTORY_PAGE_SIZE,
  pageWindow,
  parseHistoryParams,
  type HistoryParams,
} from "#/lib/history";
import { isVideoId } from "#/lib/ids";
import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for the history page and the watch page's resume position. */

export type { HistoryEntry, HistorySummary };

export type HistoryOutcome =
  | { ok: true; entries: HistoryEntry[]; hasMore: boolean }
  | { ok: false; message: string };

const fetchHistory = createServerFn({ method: "GET" })
  .inputValidator((data: HistoryParams) => parseHistoryParams({ ...data }))
  .handler(async ({ data }): Promise<HistoryOutcome> => {
    const { data: entries, error } = await searchHistory({
      client: apiClient(),
      query: { q: data.q, unrated: data.unrated, ...pageWindow(data) },
    });
    if (entries) {
      return {
        ok: true,
        entries: entries.slice(0, HISTORY_PAGE_SIZE),
        hasMore: entries.length > HISTORY_PAGE_SIZE,
      };
    }
    return {
      ok: false,
      message: apiErrorMessage(
        error,
        "Couldn't load your history. Try again later.",
      ),
    };
  });

/** One page of watch history, optionally searched or only the unrated. */
export function historyQuery(params: HistoryParams) {
  return queryOptions({
    queryKey: ["history", params],
    queryFn: () => fetchHistory({ data: params }),
  });
}

const fetchHistorySummary = createServerFn({ method: "GET" }).handler(
  async (): Promise<HistorySummary> => {
    const { data } = await getHistorySummary({
      client: apiClient(),
      throwOnError: true,
    });
    return data;
  },
);

/** How many videos were watched and how many of them are still unrated. */
export const historySummaryQuery = queryOptions({
  queryKey: ["history", "summary"],
  queryFn: () => fetchHistorySummary(),
});

/**
 * Where to resume `videoId` in seconds, or null to start from the beginning.
 * Never fails: without a saved position the video just starts at 0.
 */
export const fetchResumePosition = createServerFn({ method: "GET" })
  .inputValidator((data: { videoId: string }) => {
    if (typeof data.videoId !== "string" || !isVideoId(data.videoId)) {
      throw new Error("Not a video id");
    }
    return { videoId: data.videoId };
  })
  .handler(async ({ data }): Promise<number | null> => {
    try {
      const { data: entry } = await getHistoryEntry({
        client: apiClient(),
        path: { video_id: data.videoId },
      });
      return entry?.resume_position ?? null;
    } catch {
      return null;
    }
  });
