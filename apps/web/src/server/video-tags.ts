import {
  addVideoTag,
  removeVideoTag,
  suggestTags,
  type VideoTagOut,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { isVideoId } from "#/lib/ids";
import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for adding and removing a video's tags by hand. */

export type TagEditResult =
  { ok: true; tags: VideoTagOut[] } | { ok: false; message: string };

function videoIdInput(data: { videoId: string }) {
  if (typeof data.videoId !== "string" || !isVideoId(data.videoId)) {
    throw new Error("Not a video id");
  }
  return { videoId: data.videoId };
}

/** Tag a video by hand; resolves to the video's tags, or why it failed. */
export const addTagToVideo = createServerFn({ method: "POST" })
  .inputValidator((data: { videoId: string; label: string }) => {
    if (typeof data.label !== "string") throw new Error("label must be text");
    return { ...videoIdInput(data), label: data.label };
  })
  .handler(async ({ data }): Promise<TagEditResult> => {
    const {
      data: tags,
      error,
      response,
    } = await addVideoTag({
      client: apiClient(),
      path: { video_id: data.videoId },
      body: { label: data.label },
    });
    if (tags) return { ok: true, tags };
    return {
      ok: false,
      message: apiErrorMessage(
        error,
        response?.status === 404
          ? "That video doesn't exist."
          : "Couldn't add that tag. Try again.",
      ),
    };
  });

/** Remove a tag from a video; resolves to the video's remaining tags. */
export const removeTagFromVideo = createServerFn({ method: "POST" })
  .inputValidator((data: { videoId: string; slug: string }) => {
    if (typeof data.slug !== "string" || data.slug === "") {
      throw new Error("slug must be text");
    }
    return { ...videoIdInput(data), slug: data.slug };
  })
  .handler(async ({ data }): Promise<TagEditResult> => {
    const {
      data: tags,
      error,
      response,
    } = await removeVideoTag({
      client: apiClient(),
      path: { video_id: data.videoId, slug: data.slug },
    });
    if (tags) return { ok: true, tags };
    return {
      ok: false,
      message: apiErrorMessage(
        error,
        `Couldn't remove that tag (${response?.status}). Try again.`,
      ),
    };
  });

const fetchTagSuggestions = createServerFn({ method: "GET" })
  .inputValidator((data: { q: string }) => {
    if (typeof data.q !== "string") throw new Error("q must be text");
    return { q: data.q.slice(0, 100) };
  })
  .handler(async ({ data }) => {
    const { data: suggestions } = await suggestTags({
      client: apiClient(),
      query: { q: data.q },
      throwOnError: true,
    });
    return suggestions;
  });

/** Existing tags to offer for what's been typed so far. */
export const tagSuggestionsQuery = (q: string) =>
  queryOptions({
    queryKey: ["tag-suggestions", q],
    queryFn: () => fetchTagSuggestions({ data: { q } }),
    staleTime: 30 * 1000,
  });
