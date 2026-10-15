/**
 * What Today says around its feed: when the next one arrives, what is left
 * over from the last one and what is queued. Pure, so server and client say
 * the same and the wording is easy to test.
 */

/** "06:00" as "6:00": the hour without its leading zero, the minutes as they are. */
export function formatClock(time: string): string {
  const match = /^(\d{1,2}):(\d{2})/.exec(time.trim());
  if (!match) return time;
  return `${Number(match[1])}:${match[2]}`;
}

/** The minutes since midnight of `now` in `timeZone` (the browser's if it's null or unknown). */
export function minutesIntoDay(now: Date, timeZone: string | null): number {
  const read = (zone: string | undefined) => {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: zone,
      hour: "numeric",
      minute: "numeric",
      hourCycle: "h23",
    }).formatToParts(now);
    const part = (type: string) =>
      Number(parts.find((p) => p.type === type)?.value);
    return part("hour") * 60 + part("minute");
  };
  try {
    return read(timeZone ?? undefined);
  } catch {
    // Not a time zone this browser knows.
    return read(undefined);
  }
}

/**
 * When the next feed is built, from the time of day it's built at and the time
 * zone that time is in (the browser's if it's null): "Next feed at 6:00" while
 * that is still to come today, "Next feed tomorrow at 6:00" once it has passed.
 */
export function nextFeedText(
  refreshTime: string,
  now: Date,
  timeZone: string | null,
): string {
  const match = /^(\d{1,2}):(\d{2})/.exec(refreshTime.trim());
  const at = formatClock(refreshTime);
  if (!match) return `Next feed at ${at}`;
  const due = Number(match[1]) * 60 + Number(match[2]);
  return minutesIntoDay(now, timeZone) < due
    ? `Next feed at ${at}`
    : `Next feed tomorrow at ${at}`;
}

/** A feed date (`YYYY-MM-DD`) as e.g. "Wed, Oct 14". */
export function formatFeedDay(day: string): string {
  const parsed = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return day;
  return parsed.toLocaleDateString("en", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/**
 * The feed to take leftovers from: the newest of `feeds` (listed newest first,
 * as the API has them) that picked anything. An empty feed has none to give.
 */
export function previousFeedOf<T extends { item_count: number }>(
  feeds: readonly T[],
): T | null {
  return feeds.find((feed) => feed.item_count > 0) ?? null;
}

/** The heading over what's left of an earlier feed. */
export function leftoversHeading(day: string): string {
  return `Still unwatched from ${formatFeedDay(day)}`;
}

/** What the picks of a feed are left unwatched and undismissed. */
export function leftovers<
  T extends { watched: boolean; dismissed_at: string | null },
>(items: readonly T[]): T[] {
  return items.filter((item) => !item.watched && item.dismissed_at === null);
}

/** What the queue holds, in words: "Nothing in your queue", "3 videos in your queue". */
export function queueSummary(count: number): string {
  if (count <= 0) return "Nothing in your queue";
  return `${count} ${count === 1 ? "video" : "videos"} in your queue`;
}
