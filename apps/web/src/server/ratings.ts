import { deleteRating, getRating, rateVideo } from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { isGrade, type Grade } from "#/lib/grades";
import { isVideoId } from "#/lib/ids";
import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for a video's rating (the watch page's prompt and editor). */

export interface Rating {
  video_id: string;
  grade: Grade;
  value: number;
  rated_at: string;
  updated_at: string;
}

function videoIdInput(data: { videoId: string }) {
  if (typeof data.videoId !== "string" || !isVideoId(data.videoId)) {
    throw new Error("Not a video id");
  }
  return { videoId: data.videoId };
}

/** The video's rating, or null when it isn't rated. */
const fetchRating = createServerFn({ method: "GET" })
  .inputValidator(videoIdInput)
  .handler(async ({ data }): Promise<Rating | null> => {
    const {
      data: rating,
      error,
      response,
    } = await getRating({
      client: apiClient(),
      path: { video_id: data.videoId },
    });
    if (rating) return rating;
    if (response?.status === 404) return null;
    throw new Error(
      apiErrorMessage(error, `Couldn't load the rating (${response?.status})`),
    );
  });

export const ratingQuery = (videoId: string) =>
  queryOptions({
    queryKey: ["rating", videoId],
    queryFn: () => fetchRating({ data: { videoId } }),
  });

export const saveRating = createServerFn({ method: "POST" })
  .inputValidator((data: { videoId: string; grade: Grade }) => {
    if (!isGrade(data.grade)) {
      throw new Error(`Unknown grade ${String(data.grade)}`);
    }
    return { ...videoIdInput(data), grade: data.grade };
  })
  .handler(async ({ data }): Promise<Rating> => {
    const { data: rating } = await rateVideo({
      client: apiClient(),
      path: { video_id: data.videoId },
      body: { grade: data.grade },
      throwOnError: true,
    });
    return rating;
  });

export const removeRating = createServerFn({ method: "POST" })
  .inputValidator(videoIdInput)
  .handler(async ({ data }): Promise<void> => {
    const { response } = await deleteRating({
      client: apiClient(),
      path: { video_id: data.videoId },
    });
    // Already gone is fine.
    if (!response?.ok && response?.status !== 404) {
      throw new Error(`Couldn't remove the rating (${response?.status})`);
    }
  });
