/** Formatting for feed items. Pure, so server and client render the same text. */

/** `m:ss` or `h:mm:ss`, or null when the duration is unknown (RSS-only videos). */
export function formatDuration(
  seconds: number | null | undefined,
): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

const AGE_UNITS: [unit: string, seconds: number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

/** How long ago `iso` was, e.g. "3 hours ago", or null when unknown. */
export function formatAge(
  iso: string | null | undefined,
  now: Date = new Date(),
): string | null {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  const elapsed = Math.max(0, (now.getTime() - then) / 1000);
  for (const [unit, size] of AGE_UNITS) {
    const count = Math.floor(elapsed / size);
    if (count >= 1) return `${count} ${unit}${count === 1 ? "" : "s"} ago`;
  }
  return "just now";
}

const compact = new Intl.NumberFormat("en", {
  notation: "compact",
  maximumFractionDigits: 1,
});

/** "1.2K views", or null when the count is unknown. */
export function formatViews(count: number | null | undefined): string | null {
  if (count == null) return null;
  return `${compact.format(count)} ${count === 1 ? "view" : "views"}`;
}

/** A feed date (`YYYY-MM-DD`) as e.g. "Mon, Oct 12, 2026". */
export function formatFeedDate(day: string): string {
  const parsed = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return day;
  return parsed.toLocaleDateString("en", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** Whether `value` is a real calendar date in `YYYY-MM-DD` form. */
export function isFeedDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false;
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  return (
    !Number.isNaN(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}
