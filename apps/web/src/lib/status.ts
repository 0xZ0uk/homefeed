import type { ExtractorStatusOut } from "@homefeed/api-client";

/** Pure helpers for the status page. */

export type ExtractorHealth = ExtractorStatusOut["health"];

/** The windows the status page offers, in hours. */
export const STATUS_WINDOWS = [
  { hours: 24, label: "Last 24 hours" },
  { hours: 24 * 7, label: "Last 7 days" },
] as const;

export const DEFAULT_STATUS_HOURS = STATUS_WINDOWS[0].hours;

/** The `hours` search param, or the default when it isn't one of the windows. */
export function parseStatusHours(value: unknown): number {
  const hours = typeof value === "string" ? Number(value) : value;
  return STATUS_WINDOWS.some((window) => window.hours === hours)
    ? (hours as number)
    : DEFAULT_STATUS_HOURS;
}

const HEALTH_LABELS: Record<ExtractorHealth, string> = {
  ok: "Working",
  degraded: "Some failures",
  failing: "Failing",
  unknown: "No data",
};

export function healthLabel(health: ExtractorHealth): string {
  return HEALTH_LABELS[health];
}

const HEALTH_CLASSES: Record<ExtractorHealth, string> = {
  ok: "bg-green-100 text-green-800",
  degraded: "bg-amber-100 text-amber-900",
  failing: "bg-red-100 text-red-800",
  unknown: "bg-gray-100 text-gray-700",
};

/** Tailwind classes for a health badge. */
export function healthBadgeClass(health: ExtractorHealth): string {
  return HEALTH_CLASSES[health];
}

/** One sentence on the overall health, for the top of the page. */
export function healthSummary(health: ExtractorHealth): string {
  switch (health) {
    case "ok":
      return "YouTube extraction is working.";
    case "degraded":
      return "Some requests to YouTube failed, but extraction mostly works.";
    case "failing":
      return "YouTube extraction is failing. The feed keeps working from cached data; updating yt-dlp usually fixes this.";
    case "unknown":
      return "Nothing has been fetched from YouTube in this window.";
  }
}

const OPERATION_LABELS: Record<string, string> = {
  get_video: "Video metadata",
  get_formats: "Stream formats",
  get_captions: "Captions",
  get_comments: "Comments",
  get_related: "Related videos",
  search: "Search",
  get_channel_uploads: "Channel uploads",
  get_channel_feed: "Channel RSS feeds",
  get_featured_channels: "Featured channels",
  resolve_url: "URL resolution",
  open_media: "Media streaming",
  probe_dash_ranges: "Stream index probing",
};

/** A Gateway operation as shown, e.g. "Video metadata" for `get_video`. */
export function operationLabel(operation: string): string {
  return OPERATION_LABELS[operation] ?? operation;
}

/** How long ago `iso` was, e.g. "just now", "5 min ago", "3 h ago", "2 d ago". */
export function formatAgo(
  iso: string | null | undefined,
  now: Date = new Date(),
): string {
  if (!iso) return "–";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  const minutes = Math.floor((now.getTime() - at.getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.floor(hours / 24)} d ago`;
}

/** A duration in milliseconds, e.g. "850 ms" or "1.2 s", or "–" when unknown. */
export function formatMilliseconds(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "–";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}
