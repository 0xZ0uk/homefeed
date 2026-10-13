/**
 * The pure parts of the feed grid: filtering by length (the chips above it),
 * and giving each channel a colour for its avatar and placeholder thumbnails.
 */

export type LengthFilter = "all" | "short" | "medium" | "long";

export const LENGTH_FILTERS: { value: LengthFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "short", label: "Under 10 min" },
  { value: "medium", label: "10–30 min" },
  { value: "long", label: "Over 30 min" },
];

const TEN_MINUTES = 600;
const THIRTY_MINUTES = 1800;

/** Whether a video of `seconds` belongs under `filter`. Unknown lengths only
 * show under "all". */
export function matchesLength(
  seconds: number | null | undefined,
  filter: LengthFilter,
): boolean {
  if (filter === "all") return true;
  if (seconds == null || seconds < 0) return false;
  if (filter === "short") return seconds < TEN_MINUTES;
  if (filter === "medium")
    return seconds < THIRTY_MINUTES && seconds >= TEN_MINUTES;
  return seconds >= THIRTY_MINUTES;
}

export function isLengthFilter(value: unknown): value is LengthFilter {
  return LENGTH_FILTERS.some((filter) => filter.value === value);
}

/** Channel colours: muted tones, all dark enough for white text. */
export const CHANNEL_COLORS = [
  "oklch(0.42 0.12 262)", // navy
  "oklch(0.42 0.14 25)", // oxblood
  "oklch(0.44 0.1 155)", // bottle green
  "oklch(0.4 0.03 250)", // slate
  "oklch(0.4 0.11 320)", // plum
  "oklch(0.5 0.11 70)", // mustard
  "oklch(0.44 0.08 205)", // teal
  "oklch(0.45 0.12 45)", // rust
] as const;

/** A stable colour per channel (FNV-1a over its id), so a channel's videos
 * share one. */
export function channelColor(channelId: string): string {
  let hash = 0x811c9dc5;
  for (const char of channelId) {
    hash = Math.imul(hash ^ char.charCodeAt(0), 0x01000193);
  }
  return (
    CHANNEL_COLORS[(hash >>> 0) % CHANNEL_COLORS.length] ?? CHANNEL_COLORS[0]
  );
}
