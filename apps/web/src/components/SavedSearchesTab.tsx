import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import {
  SCHEDULES,
  describeFilters,
  describeLastRun,
  searchParamsFor,
  type Schedule,
} from "#/lib/search";
import {
  removeSavedSearch,
  savedSearchesQuery,
  setSavedSearchSchedule,
  type SavedSearch,
} from "#/server/saved-searches";

/**
 * Saved searches: each runs on its schedule with the daily feed build and its
 * top results become candidates. New ones are saved from the search page.
 */
export function SavedSearchesTab() {
  const { data: searches } = useSuspenseQuery(savedSearchesQuery);
  // One "now" per render pass keeps every "last run" age consistent.
  const [now] = useState(() => new Date());

  return (
    <div className="flex flex-col gap-6">
      <p className="text-gray-600">
        Each saved search runs daily or weekly with the feed build, and its top
        results are considered for your feed, marked with the search they came
        from.{" "}
        <Link to="/search" className="underline">
          Search YouTube
        </Link>{" "}
        to save a new one.
      </p>
      {searches.length === 0 ? (
        <p className="rounded border border-dashed p-6 text-gray-600">
          No saved searches yet. Run a search and choose “Save search” to add
          one.
        </p>
      ) : (
        <ul className="flex flex-col divide-y" aria-label="Saved searches">
          {searches.map((search) => (
            <SavedSearchRow key={search.id} search={search} now={now} />
          ))}
        </ul>
      )}
    </div>
  );
}

function SavedSearchRow({ search, now }: { search: SavedSearch; now: Date }) {
  const queryClient = useQueryClient();
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: savedSearchesQuery.queryKey });
  const schedule = useMutation({
    mutationFn: (value: Schedule) =>
      setSavedSearchSchedule({ data: { id: search.id, schedule: value } }),
    onSettled: invalidate,
  });
  const remove = useMutation({
    mutationFn: () => removeSavedSearch({ data: { id: search.id } }),
    onSettled: invalidate,
  });
  const filters = describeFilters(search.filters);
  const selectId = `saved-search-${search.id}-schedule`;
  const shownSchedule = schedule.isPending
    ? schedule.variables
    : search.schedule;

  return (
    <li className="flex flex-col gap-2 py-3">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <div className="min-w-0">
          <Link
            to="/search"
            search={searchParamsFor(search.query, search.filters)}
            className="font-medium break-words hover:underline"
          >
            {search.query}
          </Link>
          {filters && (
            <span className="text-sm text-gray-600"> · {filters}</span>
          )}
        </div>
        <div className="flex items-center gap-4 text-sm">
          <label htmlFor={selectId} className="sr-only">
            How often to run “{search.query}”
          </label>
          <select
            id={selectId}
            value={shownSchedule}
            disabled={schedule.isPending}
            onChange={(event) => {
              const picked = SCHEDULES.find(
                (s) => s.value === event.target.value,
              );
              if (picked) schedule.mutate(picked.value);
            }}
            className="rounded border px-2 py-1 disabled:opacity-50"
          >
            {SCHEDULES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
            aria-label={`Delete saved search ${search.query}`}
            className="text-red-700 underline disabled:opacity-50"
          >
            Delete
          </button>
        </div>
      </div>
      <p
        className={
          search.last_error ? "text-sm text-red-700" : "text-sm text-gray-600"
        }
        suppressHydrationWarning
      >
        {describeLastRun(search, now)}
      </p>
      {(schedule.isError || remove.isError) && (
        <p role="alert" className="text-sm text-red-600">
          {remove.isError
            ? "Couldn't delete that search. Try again."
            : "Couldn't change the schedule. Try again."}
        </p>
      )}
    </li>
  );
}
