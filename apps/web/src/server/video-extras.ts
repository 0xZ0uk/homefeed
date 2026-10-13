import {
  getSponsorSegments,
  type SponsorSegmentOut,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { isVideoId } from "#/lib/ids";
import { apiClient, apiErrorMessage } from "#/server/api";

/** The watch page's extras: SponsorBlock segments. */

export type SponsorSegment = SponsorSegmentOut;

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
