/**
 * Watch history: URL parsing, paging, progress labels, and what rating a
 * video from the list changes. Pure.
 */

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
  /** Only the watched videos that aren't rated yet. */
  unrated?: boolean;
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
  if (raw.unrated === true || raw.unrated === "true") params.unrated = true;
  return params;
}

/**
 * `params` with `changes` applied, e.g. a new search or the filter turned on.
 * Anything but a change of page starts over at the first page.
 */
export function paramsWith(
  params: HistoryParams,
  changes: Partial<HistoryParams>,
): HistoryParams {
  const merged: Record<string, unknown> = { ...params, ...changes };
  if (!("page" in changes)) delete merged.page;
  return parseHistoryParams(merged);
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

/** The part of a history entry that rating changes. */
interface Rateable {
  video_id: string;
  score?: number | null;
}

/**
 * `entries` once `videoId` is rated `score`. In a list of the unrated it is
 * gone; in the whole history it shows its rating.
 */
export function afterRating<T extends Rateable>(
  entries: readonly T[],
  videoId: string,
  score: number,
  unratedOnly: boolean,
): T[] {
  if (unratedOnly) return entries.filter((entry) => entry.video_id !== videoId);
  return entries.map((entry) =>
    entry.video_id === videoId ? { ...entry, score } : entry,
  );
}

/**
 * Whether a query key is a cached page of the history (see `historyQuery`):
 * of the unrated videos when `unratedOnly`, else of everything. The history's
 * other queries (its summary) are not.
 */
export function isHistoryPageKey(
  key: readonly unknown[],
  unratedOnly: boolean,
): boolean {
  const params = key[1];
  if (key[0] !== "history" || typeof params !== "object" || params === null) {
    return false;
  }
  return Boolean((params as HistoryParams).unrated) === unratedOnly;
}

/**
 * The entry to move focus to when the one at `videoId` leaves the list: the
 * next one, else the one before it, else nothing.
 */
export function neighbourOf<T extends { video_id: string }>(
  entries: readonly T[],
  videoId: string,
): T | null {
  const index = entries.findIndex((entry) => entry.video_id === videoId);
  if (index < 0) return null;
  return entries[index + 1] ?? entries[index - 1] ?? null;
}

/**
 * What is announced after rating a video from the history, e.g. "Rated 8 out
 * of 10: Sharpening a hand plane. 4 left to rate." `remaining` is how many
 * watched videos are still unrated, or null when that isn't known.
 */
export function describeRated(
  title: string,
  score: number,
  remaining: number | null,
): string {
  const rated = `Rated ${score} out of 10: ${title}.`;
  if (remaining === null) return rated;
  if (remaining <= 0) return `${rated} Everything you watched is rated.`;
  return `${rated} ${remaining} left to rate.`;
}
