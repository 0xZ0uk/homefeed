/** Display helpers for external sources. Pure, so server and client render the same text. */

import type { ExternalSource } from "@homefeed/api-client";

import { formatAge } from "#/lib/format";

export type SourceKind = ExternalSource["kind"];
export type SourceSchedule = ExternalSource["schedule"];

export const SOURCE_KINDS: readonly SourceKind[] = ["subreddit", "rss", "page"];
export const SOURCE_SCHEDULES: readonly SourceSchedule[] = [
  "hourly",
  "daily",
  "weekly",
];

export const KIND_LABELS: Record<SourceKind, string> = {
  subreddit: "Subreddit",
  rss: "RSS feed",
  page: "Link page",
};

export const SCHEDULE_LABELS: Record<SourceSchedule, string> = {
  hourly: "Hourly",
  daily: "Daily",
  weekly: "Weekly",
};

/** What to type for each kind of source. */
export const KIND_PLACEHOLDERS: Record<SourceKind, string> = {
  subreddit: "r/videos",
  rss: "https://example.com/feed.xml",
  page: "https://example.com/best-videos",
};

export function isSourceKind(value: unknown): value is SourceKind {
  return SOURCE_KINDS.includes(value as SourceKind);
}

export function isSourceSchedule(value: unknown): value is SourceSchedule {
  return SOURCE_SCHEDULES.includes(value as SourceSchedule);
}

/**
 * A source's fetch status in one line, e.g. "Checked 2 hours ago · 4 videos",
 * "Failing (3 times): HTTP Error 404 …" or "Not checked yet".
 */
export function sourceStatus(
  source: Pick<
    ExternalSource,
    | "last_fetched_at"
    | "last_success_at"
    | "consecutive_failures"
    | "last_error"
    | "last_found_count"
  >,
  now: Date = new Date(),
): string {
  if (source.consecutive_failures > 0) {
    const times =
      source.consecutive_failures === 1
        ? "once"
        : `${source.consecutive_failures} times`;
    const error = source.last_error ? `: ${source.last_error}` : "";
    return `Failing (${times})${error}`;
  }
  const checked = formatAge(source.last_success_at, now);
  if (!checked) return "Not checked yet";
  const count = source.last_found_count ?? 0;
  return `Checked ${checked} · ${count} ${count === 1 ? "video" : "videos"}`;
}
