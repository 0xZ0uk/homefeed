import {
  getComments,
  getSponsorSegments,
  type CommentOut,
  type SponsorSegmentOut,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { isVideoId } from "#/lib/ids";
import { apiClient, apiErrorMessage } from "#/server/api";

/** The watch page's extras: SponsorBlock segments and comments. */

export type Comment = CommentOut;
export type SponsorSegment = SponsorSegmentOut;

/** How many top comments the watch page loads. */
export const COMMENTS_LIMIT = 20;

function validateVideoId(data: { videoId: string }) {
  if (typeof data.videoId !== "string" || !isVideoId(data.videoId)) {
    throw new Error("Not a video id");
  }
  return { videoId: data.videoId };
}

const fetchSponsorSegments = createServerFn({ method: "GET" })
  .inputValidator(validateVideoId)
  .handler(async ({ data }): Promise<SponsorSegment[]> => {
    const {
      data: segments,
      error,
      response,
    } = await getSponsorSegments({
      client: apiClient(),
      path: { video_id: data.videoId },
    });
    if (segments) return segments;
    throw new Error(
      apiErrorMessage(
        error,
        `Couldn't load SponsorBlock segments (${response?.status})`,
      ),
    );
  });

/** The segments the player skips (none while loading or when this fails). */
export const sponsorSegmentsQuery = (videoId: string) =>
  queryOptions({
    queryKey: ["video", videoId, "segments"],
    queryFn: () => fetchSponsorSegments({ data: { videoId } }),
    staleTime: 60 * 60 * 1000,
    retry: 1,
  });

const fetchComments = createServerFn({ method: "GET" })
  .inputValidator(validateVideoId)
  .handler(async ({ data }): Promise<Comment[]> => {
    const {
      data: comments,
      error,
      response,
    } = await getComments({
      client: apiClient(),
      path: { video_id: data.videoId },
      query: { limit: COMMENTS_LIMIT },
    });
    if (comments) return comments;
    throw new Error(
      apiErrorMessage(error, `Couldn't load comments (${response?.status})`),
    );
  });

/** Top comments; only fetched once asked for (see `Comments`). */
export const commentsQuery = (videoId: string) =>
  queryOptions({
    queryKey: ["video", videoId, "comments", COMMENTS_LIMIT],
    queryFn: () => fetchComments({ data: { videoId } }),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
