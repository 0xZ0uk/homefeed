import {
  getSimilarVideos,
  getVideo,
  type SimilarVideoOut,
  type VideoOut,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { isVideoId } from "#/lib/ids";
import { apiClient, apiErrorMessage } from "#/server/api";

export type Video = VideoOut;
export type SimilarVideo = SimilarVideoOut;

/** How many similar videos "More like this" lists at most. */
export const SIMILAR_LIMIT = 8;

/** A video's metadata, or null when it doesn't exist or can't be watched. */
const fetchVideo = createServerFn({ method: "GET" })
  .inputValidator((data: { videoId: string }) => {
    if (!isVideoId(data.videoId)) throw new Error("Not a video id");
    return { videoId: data.videoId };
  })
  .handler(async ({ data }): Promise<Video | null> => {
    const {
      data: video,
      error,
      response,
    } = await getVideo({
      client: apiClient(),
      path: { video_id: data.videoId },
    });
    if (video) return video;
    if (response?.status === 404) return null;
    throw new Error(
      apiErrorMessage(error, `Couldn't load the video (${response?.status})`),
    );
  });

export const videoQuery = (videoId: string) =>
  queryOptions({
    queryKey: ["video", videoId],
    queryFn: () => fetchVideo({ data: { videoId } }),
    staleTime: 5 * 60 * 1000,
  });

/**
 * The videos like this one, best first, each with why it's listed. Empty until
 * videos have been analysed. Throws when they can't be loaded.
 */
const fetchSimilarVideos = createServerFn({ method: "GET" })
  .inputValidator((data: { videoId: string }) => {
    if (!isVideoId(data.videoId)) throw new Error("Not a video id");
    return { videoId: data.videoId };
  })
  .handler(async ({ data }): Promise<SimilarVideo[]> => {
    const {
      data: videos,
      error,
      response,
    } = await getSimilarVideos({
      client: apiClient(),
      path: { video_id: data.videoId },
      query: { limit: SIMILAR_LIMIT },
    });
    if (videos) return videos;
    throw new Error(
      apiErrorMessage(
        error,
        `Couldn't load similar videos (${response?.status})`,
      ),
    );
  });

/**
 * Only fetched when "Find more like this" is pressed (see `SimilarVideos`):
 * nothing similar is looked up, or shown, unasked.
 */
export const similarVideosQuery = (videoId: string) =>
  queryOptions({
    queryKey: ["video", videoId, "similar"],
    queryFn: () => fetchSimilarVideos({ data: { videoId } }),
    staleTime: 5 * 60 * 1000,
  });

/** Where the player loads the video's DASH manifest (proxied to the API). */
export function manifestUrl(videoId: string): string {
  return `/videos/${encodeURIComponent(videoId)}/manifest.mpd`;
}
