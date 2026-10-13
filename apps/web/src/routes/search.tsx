import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { AppHeader } from "#/components/AppHeader";
import { showsThumbnails, type DisplayPrefs } from "#/lib/display";
import { formatDuration, formatViews } from "#/lib/format";
import {
  DURATIONS,
  QUERY_MAX_LENGTH,
  SCHEDULES,
  SORTS,
  UPLOAD_DATES,
  describeFilters,
  filtersOf,
  parseSearchParams,
  type Schedule,
  type SearchParams,
} from "#/lib/search";
import { displayPrefsQuery } from "#/server/display";
import { saveSearch, savedSearchesQuery } from "#/server/saved-searches";
import { searchQuery, type SearchResult } from "#/server/search";

/**
 * Search YouTube with its filters, and save a search so its results flow into
 * the candidates on a schedule. Results are one fixed page: no "load more".
 */
export const Route = createFileRoute("/search")({
  validateSearch: (search: Record<string, unknown>): SearchParams =>
    parseSearchParams(search),
  head: () => ({ meta: [{ title: "Search · Homefeed" }] }),
  loaderDeps: ({ search }) => search,
  loader: async ({ context, deps }) => {
    await Promise.all([
      context.queryClient.ensureQueryData(displayPrefsQuery),
      deps.q ? context.queryClient.ensureQueryData(searchQuery(deps)) : null,
    ]);
  },
  component: Search,
});

function Search() {
  const params = Route.useSearch();

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <AppHeader />
      <h2 className="text-xl font-semibold">Search YouTube</h2>
      {/* Remount when the URL changes so the fields show the current search. */}
      <SearchForm key={JSON.stringify(params)} params={params} />
      {params.q ? (
        <>
          <SaveSearch params={params} />
          <Results params={params} />
        </>
      ) : (
        <p className="text-gray-600">
          Search for videos on YouTube. Save a search to have its newest results
          considered for your daily feed.
        </p>
      )}
    </main>
  );
}

function SearchForm({ params }: { params: SearchParams }) {
  const navigate = useNavigate({ from: "/search" });
  const [fields, setFields] = useState(() => ({
    q: params.q ?? "",
    ...filtersOf(params),
  }));

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void navigate({ search: parseSearchParams(fields) });
  }

  return (
    <form onSubmit={onSubmit} role="search" className="flex flex-col gap-3">
      <div className="flex gap-2">
        <label htmlFor="search-query" className="sr-only">
          Search query
        </label>
        <input
          id="search-query"
          type="search"
          value={fields.q}
          onChange={(event) => setFields({ ...fields, q: event.target.value })}
          placeholder="e.g. hand plane restoration"
          maxLength={QUERY_MAX_LENGTH}
          required
          className="min-w-0 flex-1 rounded border px-3 py-2"
        />
        <button
          type="submit"
          className="rounded bg-black px-3 py-2 font-medium text-white"
        >
          Search
        </button>
      </div>
      <div className="flex flex-wrap gap-4 text-sm">
        <FilterSelect
          id="search-sort"
          label="Sort by"
          value={fields.sort}
          options={SORTS}
          onChange={(sort) => setFields({ ...fields, sort })}
        />
        <FilterSelect
          id="search-upload-date"
          label="Uploaded"
          value={fields.upload_date ?? ""}
          options={[{ value: "", label: "Any time" }, ...UPLOAD_DATES]}
          onChange={(value) =>
            setFields({ ...fields, upload_date: value || null })
          }
        />
        <FilterSelect
          id="search-duration"
          label="Length"
          value={fields.duration ?? ""}
          options={[{ value: "", label: "Any length" }, ...DURATIONS]}
          onChange={(value) =>
            setFields({ ...fields, duration: value || null })
          }
        />
      </div>
    </form>
  );
}

function FilterSelect<T extends string>({
  id,
  label,
  value,
  options,
  onChange,
}: {
  id: string;
  label: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-gray-700">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => {
          const picked = options.find((o) => o.value === event.target.value);
          if (picked) onChange(picked.value);
        }}
        className="rounded border px-2 py-1"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function SaveSearch({ params }: { params: SearchParams }) {
  const queryClient = useQueryClient();
  const [schedule, setSchedule] = useState<Schedule>("daily");
  const mutation = useMutation({
    mutationFn: () => saveSearch({ data: { params, schedule } }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: savedSearchesQuery.queryKey,
      }),
  });
  const result = mutation.data;
  const filters = describeFilters(filtersOf(params));
  const schedules = SCHEDULES.filter((s) => s.value !== "paused");

  return (
    <div className="flex flex-col gap-2 rounded border p-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="min-w-0 flex-1">
          <span className="font-medium">“{params.q}”</span>
          {filters && (
            <span className="text-sm text-gray-600"> · {filters}</span>
          )}
        </p>
        <FilterSelect
          id="save-search-schedule"
          label="Run"
          value={schedule}
          options={schedules}
          onChange={setSchedule}
        />
        <button
          type="button"
          disabled={mutation.isPending}
          onClick={() => mutation.mutate()}
          className="rounded border px-3 py-1 text-sm font-medium disabled:opacity-50"
        >
          {mutation.isPending ? "Saving…" : "Save search"}
        </button>
      </div>
      <p role="status" className="min-h-5 text-sm">
        {mutation.isError && (
          <span className="text-red-600">
            Couldn't save the search. Try again later.
          </span>
        )}
        {result?.ok === false && (
          <span className="text-red-600">{result.message}</span>
        )}
        {result?.ok === true && (
          <span className="text-gray-700">
            {result.created
              ? "Saved. Its results will be considered for your feed. "
              : "This search is already saved. "}
            <Link
              to="/curation"
              search={{ tab: "searches" }}
              className="underline"
            >
              Manage saved searches
            </Link>
          </span>
        )}
      </p>
    </div>
  );
}

function Results({ params }: { params: SearchParams }) {
  const { data: outcome } = useSuspenseQuery(searchQuery(params));
  const { data: display } = useSuspenseQuery(displayPrefsQuery);

  if (!outcome.ok) {
    return (
      <p role="alert" className="text-red-600">
        {outcome.message}
      </p>
    );
  }
  if (outcome.results.length === 0) {
    return (
      <p className="text-gray-600">
        No videos found. Try fewer words or looser filters.
      </p>
    );
  }
  return (
    <ol className="flex flex-col divide-y" aria-label="Search results">
      {outcome.results.map((result) => (
        <ResultRow key={result.id} result={result} display={display} />
      ))}
    </ol>
  );
}

function ResultRow({
  result,
  display,
}: {
  result: SearchResult;
  display: DisplayPrefs;
}) {
  const duration = formatDuration(result.duration_seconds);
  const views = display.viewCounts ? formatViews(result.view_count) : null;
  const thumbnails = showsThumbnails(display);
  const params = { videoId: result.id };
  const live =
    result.live_status === "is_live" || result.live_status === "is_upcoming";

  return (
    <li className="flex gap-4 py-3">
      {thumbnails && (
        // Mouse-only; the title link is the one in the tab order.
        <Link
          to="/watch/$videoId"
          params={params}
          tabIndex={-1}
          aria-hidden="true"
          className="relative aspect-video w-40 shrink-0 overflow-hidden rounded bg-gray-200"
        >
          {result.thumbnail_url && (
            <img
              src={result.thumbnail_url}
              alt=""
              loading="lazy"
              className="size-full object-cover"
            />
          )}
          {duration && (
            <span className="absolute right-1 bottom-1 rounded bg-black/80 px-1 text-xs text-white tabular-nums">
              {duration}
            </span>
          )}
        </Link>
      )}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <h3 className="font-medium">
          <Link
            to="/watch/$videoId"
            params={params}
            className="hover:underline"
          >
            {result.title}
          </Link>
        </h3>
        <p className="flex flex-wrap gap-x-2 text-sm text-gray-600">
          <span>{result.channel_title}</span>
          {duration && !thumbnails && (
            <span className="tabular-nums">· {duration}</span>
          )}
          {views && <span>· {views}</span>}
          {live && (
            <span>
              · {result.live_status === "is_live" ? "Live now" : "Upcoming"}
            </span>
          )}
        </p>
        {result.description && (
          <p className="line-clamp-2 text-sm text-gray-500">
            {result.description}
          </p>
        )}
      </div>
    </li>
  );
}
