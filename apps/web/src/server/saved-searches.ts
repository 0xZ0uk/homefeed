import {
  addSavedSearch,
  deleteSavedSearch,
  listSavedSearches,
  updateSavedSearch,
  type SavedSearch,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import {
  SCHEDULES,
  filtersOf,
  parseSearchParams,
  type Schedule,
  type SearchParams,
} from "#/lib/search";
import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for saved searches (search page and curation tab). */

export type { SavedSearch };

export type SavedSearchResult =
  | { ok: true; search: SavedSearch; created: boolean }
  | { ok: false; message: string };

function checkSchedule(schedule: unknown): Schedule {
  const found = SCHEDULES.find((s) => s.value === schedule);
  if (!found) throw new Error("schedule must be daily, weekly or paused");
  return found.value;
}

function checkId(id: unknown): number {
  if (!Number.isInteger(id) || (id as number) < 1) {
    throw new Error("id must be a positive integer");
  }
  return id as number;
}

const getSavedSearches = createServerFn({ method: "GET" }).handler(async () => {
  const { data } = await listSavedSearches({
    client: apiClient(),
    throwOnError: true,
  });
  return data;
});

export const savedSearchesQuery = queryOptions({
  queryKey: ["saved-searches"],
  queryFn: () => getSavedSearches(),
});

/** Save the search in `params` (its query and filters) on `schedule`. */
export const saveSearch = createServerFn({ method: "POST" })
  .inputValidator((data: { params: SearchParams; schedule: Schedule }) => {
    const params = parseSearchParams({ ...data.params });
    if (!params.q) throw new Error("q must be a non-blank string");
    return {
      params: { ...params, q: params.q },
      schedule: checkSchedule(data.schedule),
    };
  })
  .handler(async ({ data }): Promise<SavedSearchResult> => {
    const {
      data: search,
      error,
      response,
    } = await addSavedSearch({
      client: apiClient(),
      body: {
        query: data.params.q,
        filters: filtersOf(data.params),
        schedule: data.schedule,
      },
    });
    if (search) {
      return { ok: true, search, created: response?.status === 201 };
    }
    return {
      ok: false,
      message: apiErrorMessage(
        error,
        "Couldn't save the search. Try again later.",
      ),
    };
  });

/** Change how often a saved search runs (or pause it). */
export const setSavedSearchSchedule = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number; schedule: Schedule }) => ({
    id: checkId(data.id),
    schedule: checkSchedule(data.schedule),
  }))
  .handler(async ({ data }): Promise<SavedSearch> => {
    const { data: search } = await updateSavedSearch({
      client: apiClient(),
      path: { search_id: data.id },
      body: { schedule: data.schedule },
      throwOnError: true,
    });
    return search;
  });

export const removeSavedSearch = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number }) => ({ id: checkId(data.id) }))
  .handler(async ({ data }) => {
    await deleteSavedSearch({
      client: apiClient(),
      path: { search_id: data.id },
      throwOnError: true,
    });
  });
