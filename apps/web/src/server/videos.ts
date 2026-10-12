import { getVideo, type VideoOut } from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { isVideoId } from "#/lib/ids";
import { apiClient, apiErrorMessage } from "#/server/api";

export type Video = VideoOut;

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

/** Where the player loads the video's DASH manifest (proxied to the API). */
export function manifestUrl(videoId: string): string {
  return `/videos/${encodeURIComponent(videoId)}/manifest.mpd`;
}
