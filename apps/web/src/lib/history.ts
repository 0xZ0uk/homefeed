/** Watch history: URL parsing, paging and progress labels. Pure. */

import { formatDuration } from "#/lib/format";

/** Longest query the API accepts. */
export const HISTORY_QUERY_MAX_LENGTH = 200;

/** Videos per history page. */
export const HISTORY_PAGE_SIZE = 50;

/** The history page's URL state; every field is optional. */
export interface HistoryParams {
  q?: string;
  /** 1-based; omitted for the first page. */
  page?: number;
}

/**
 * The history page's URL search params, dropping anything unknown and the
 * defaults (so equal searches have equal URLs).
 */
export function parseHistoryParams(
  raw: Record<string, unknown>,
): HistoryParams {
  const params: HistoryParams = {};
  const q =
    typeof raw.q === "string"
      ? raw.q.split(/\s+/).filter(Boolean).join(" ")
      : typeof raw.q === "number"
        ? String(raw.q)
        : "";
  if (q) params.q = q.slice(0, HISTORY_QUERY_MAX_LENGTH);
  const page = typeof raw.page === "string" ? Number(raw.page) : raw.page;
  if (typeof page === "number" && Number.isInteger(page) && page > 1) {
    params.page = Math.min(page, 10_000);
  }
  return params;
}

/** The API's `limit` and `offset` for a page, asking for one extra entry to
 * tell whether there is a next page. */
export function pageWindow(params: HistoryParams): {
  limit: number;
  offset: number;
} {
  return {
    limit: HISTORY_PAGE_SIZE + 1,
    offset: ((params.page ?? 1) - 1) * HISTORY_PAGE_SIZE,
  };
}

export interface Progress {
  position: number;
  duration?: number | null;
  finished: boolean;
  resume_position?: number | null;
}

/**
 * Where I am in a video, e.g. "Stopped at 12:34 of 40:00", "Finished", or
 * null when there's nothing to resume and it was never finished.
 */
export function describeProgress(entry: Progress): string | null {
  if (entry.resume_position != null) {
    const at = formatDuration(entry.resume_position);
    const of = formatDuration(entry.duration);
    return of ? `Stopped at ${at} of ${of}` : `Stopped at ${at}`;
  }
  return entry.finished ? "Finished" : null;
}

/** How far through the video the resume position is, 0 to 1, or null. */
export function progressFraction(entry: Progress): number | null {
  if (entry.resume_position == null || !entry.duration) return null;
  return Math.min(1, Math.max(0, entry.resume_position / entry.duration));
}
