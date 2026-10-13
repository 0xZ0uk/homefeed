import { getTag, type TagDetail } from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import {
  isTagSlug,
  parseTagParams,
  tagWindow,
  type TagParams,
} from "#/lib/tags";
import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for the tag page. */

export type { TagDetail };

/** A tag and one page of its videos, or null when there's no such tag. */
const fetchTag = createServerFn({ method: "GET" })
  .inputValidator((data: { slug: string } & TagParams) => {
    if (typeof data.slug !== "string" || !isTagSlug(data.slug)) {
      throw new Error("Not a tag slug");
    }
    return { slug: data.slug, ...parseTagParams({ ...data }) };
  })
  .handler(async ({ data }): Promise<TagDetail | null> => {
    const {
      data: detail,
      error,
      response,
    } = await getTag({
      client: apiClient(),
      path: { slug: data.slug },
      query: tagWindow(data),
    });
    if (detail) return detail;
    if (response?.status === 404) return null;
    throw new Error(
      apiErrorMessage(error, `Couldn't load the tag (${response?.status})`),
    );
  });

export const tagQuery = (slug: string, params: TagParams) =>
  queryOptions({
    queryKey: ["tag", slug, params],
    queryFn: () => fetchTag({ data: { slug, ...params } }),
  });
