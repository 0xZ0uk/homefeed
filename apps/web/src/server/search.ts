import { searchVideos, type SearchResult } from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { filtersOf, parseSearchParams, type SearchParams } from "#/lib/search";
import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for the search page. */

export type { SearchResult };

export type SearchOutcome =
  { ok: true; results: SearchResult[] } | { ok: false; message: string };

const fetchSearch = createServerFn({ method: "GET" })
  .inputValidator((data: SearchParams) => {
    const params = parseSearchParams({ ...data });
    if (!params.q) throw new Error("q must be a non-blank string");
    return { ...params, q: params.q };
  })
  .handler(async ({ data }): Promise<SearchOutcome> => {
    const {
      data: results,
      error,
      response,
    } = await searchVideos({
      client: apiClient(),
      query: { q: data.q, ...filtersOf(data) },
    });
    if (results) return { ok: true, results };
    return {
      ok: false,
      message:
        response?.status === 502
          ? "YouTube couldn't be reached. Try again in a few minutes."
          : apiErrorMessage(
              error,
              "Couldn't search right now. Try again later.",
            ),
    };
  });

/** YouTube's results for a search (`params.q` must be set). */
export function searchQuery(params: SearchParams) {
  return queryOptions({
    queryKey: ["search", params],
    queryFn: () => fetchSearch({ data: params }),
    // Results barely change within minutes; don't re-ask YouTube on every visit.
    staleTime: 5 * 60 * 1000,
  });
}
