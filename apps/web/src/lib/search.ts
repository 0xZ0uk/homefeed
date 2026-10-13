/** Search filters and saved-search schedules: options, URL parsing and labels. Pure. */

import { formatAge } from "#/lib/format";

export const SORTS = [
  { value: "relevance", label: "Relevance" },
  { value: "upload_date", label: "Newest first" },
  { value: "view_count", label: "Most viewed" },
  { value: "rating", label: "Highest rated" },
] as const;
export type Sort = (typeof SORTS)[number]["value"];

export const UPLOAD_DATES = [
  { value: "hour", label: "Last hour" },
  { value: "today", label: "Today" },
  { value: "week", label: "This week" },
  { value: "month", label: "This month" },
  { value: "year", label: "This year" },
] as const;
export type UploadDate = (typeof UPLOAD_DATES)[number]["value"];

export const DURATIONS = [
  { value: "short", label: "Under 4 minutes" },
  { value: "medium", label: "4–20 minutes" },
  { value: "long", label: "Over 20 minutes" },
] as const;
export type Duration = (typeof DURATIONS)[number]["value"];

export const SCHEDULES = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "paused", label: "Paused" },
] as const;
export type Schedule = (typeof SCHEDULES)[number]["value"];

/** Longest query the API accepts. */
export const QUERY_MAX_LENGTH = 200;

export interface Filters {
  sort?: Sort;
  upload_date?: UploadDate | null;
  duration?: Duration | null;
}

/** The search page's URL state; every field is optional. */
export interface SearchParams {
  q?: string;
  sort?: Sort;
  upload_date?: UploadDate;
  duration?: Duration;
}

function pick<T extends string>(
  options: readonly { value: T }[],
  value: unknown,
): T | undefined {
  return options.find((option) => option.value === value)?.value;
}

/**
 * The search page's URL search params, dropping anything unknown and the
 * defaults (so equal searches have equal URLs).
 */
export function parseSearchParams(raw: Record<string, unknown>): SearchParams {
  const params: SearchParams = {};
  const q =
    typeof raw.q === "string"
      ? raw.q.split(/\s+/).filter(Boolean).join(" ")
      : typeof raw.q === "number"
        ? String(raw.q)
        : "";
  if (q) params.q = q.slice(0, QUERY_MAX_LENGTH);
  const sort = pick(SORTS, raw.sort);
  if (sort && sort !== "relevance") params.sort = sort;
  const uploadDate = pick(UPLOAD_DATES, raw.upload_date);
  if (uploadDate) params.upload_date = uploadDate;
  const duration = pick(DURATIONS, raw.duration);
  if (duration) params.duration = duration;
  return params;
}

/** The filters part of the search params, in the API's shape. */
export function filtersOf(params: SearchParams): Required<Filters> {
  return {
    sort: params.sort ?? "relevance",
    upload_date: params.upload_date ?? null,
    duration: params.duration ?? null,
  };
}

/** Search params that open a saved search on the search page. */
export function searchParamsFor(query: string, filters: Filters): SearchParams {
  return parseSearchParams({ q: query, ...filters });
}

/**
 * The non-default filters in words, e.g. "Newest first · This week · Over 20
 * minutes", or null for a plain search.
 */
export function describeFilters(filters: Filters): string | null {
  const parts: (string | undefined)[] = [
    filters.sort && filters.sort !== "relevance"
      ? SORTS.find((s) => s.value === filters.sort)?.label
      : undefined,
    UPLOAD_DATES.find((d) => d.value === filters.upload_date)?.label,
    DURATIONS.find((d) => d.value === filters.duration)?.label,
  ].filter((part) => part !== undefined);
  return parts.length ? parts.join(" · ") : null;
}

export interface RunState {
  schedule: Schedule;
  last_run_at: string | null;
  last_found_count: number | null;
  last_error: string | null;
}

/** How a saved search last went, e.g. "Last run 3 hours ago: 10 videos". */
export function describeLastRun(
  search: RunState,
  now: Date = new Date(),
): string {
  if (!search.last_run_at) {
    return search.schedule === "paused"
      ? "Paused before its first run."
      : "Runs with the next daily feed build.";
  }
  const age = formatAge(search.last_run_at, now) ?? "at an unknown time";
  if (search.last_error) return `Last run ${age} failed: ${search.last_error}`;
  const count = search.last_found_count ?? 0;
  return `Last run ${age}: ${count} ${count === 1 ? "video" : "videos"}.`;
}
