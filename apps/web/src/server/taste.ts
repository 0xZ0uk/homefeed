import { getTaste } from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { TASTE_DAYS, type Taste } from "#/lib/taste";
import { apiClient } from "#/server/api";

/** Server functions for the Taste page. */

const fetchTaste = createServerFn({ method: "GET" }).handler(
  async (): Promise<Taste> => {
    const { data } = await getTaste({
      client: apiClient(),
      query: { days: TASTE_DAYS },
      throwOnError: true,
    });
    return data;
  },
);

/**
 * What the app has learned about you: per followed or muted topic its picks,
 * watching and ratings, the channels' preferences, the channels you rate well
 * without following, and the signals you give. Refetch it (under the "taste"
 * key) after anything that changes topics, channels or ratings.
 */
export const tasteQuery = queryOptions({
  queryKey: ["taste"],
  queryFn: () => fetchTaste(),
});
