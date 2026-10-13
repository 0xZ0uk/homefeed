/**
 * The pure parts of the feed grid: filtering by length (the chips above it),
 * sorting, and giving each channel a colour for its avatar and placeholder
 * thumbnails.
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

export type FeedSort =
  | "ranked"
  | "recent"
  | "oldest"
  | "most-viewed"
  | "least-viewed"
  | "channel-score"
  | "shortest"
  | "longest";

export const FEED_SORTS: { value: FeedSort; label: string }[] = [
  { value: "ranked", label: "Ranked for you" },
  { value: "recent", label: "Most recent" },
  { value: "oldest", label: "Oldest" },
  { value: "most-viewed", label: "Most viewed" },
  { value: "least-viewed", label: "Least viewed" },
  { value: "channel-score", label: "Channel score" },
  { value: "shortest", label: "Shortest" },
  { value: "longest", label: "Longest" },
];

/** What sorting reads from a feed item. */
export interface SortableItem {
  published_at: string | null;
  view_count: number | null;
  duration_seconds: number | null;
  breakdown: { channel: number };
}

/** The value each sort orders by, and whether bigger comes first. */
const SORT_KEYS: Record<
  Exclude<FeedSort, "ranked">,
  { key: (item: SortableItem) => number | null; descending: boolean }
> = {
  recent: { key: (item) => publishedTime(item), descending: true },
  oldest: { key: (item) => publishedTime(item), descending: false },
  "most-viewed": { key: (item) => item.view_count, descending: true },
  "least-viewed": { key: (item) => item.view_count, descending: false },
  "channel-score": { key: (item) => item.breakdown.channel, descending: true },
  shortest: { key: (item) => item.duration_seconds, descending: false },
  longest: { key: (item) => item.duration_seconds, descending: true },
};

/** `items` in `sort` order, as a new array. "ranked" keeps the feed's own
 * order, which also breaks ties; unknown values (no date, views or length)
 * go last either way. */
export function sortFeedItems<T extends SortableItem>(
  items: readonly T[],
  sort: FeedSort,
): T[] {
  if (sort === "ranked") return [...items];
  const { key, descending } = SORT_KEYS[sort];
  return items
    .map((item, index) => ({ item, index, value: key(item) }))
    .sort((a, b) => {
      if (a.value === b.value) return a.index - b.index;
      if (a.value === null) return 1;
      if (b.value === null) return -1;
      return descending ? b.value - a.value : a.value - b.value;
    })
    .map(({ item }) => item);
}

export function isFeedSort(value: unknown): value is FeedSort {
  return FEED_SORTS.some((sort) => sort.value === value);
}

function publishedTime(item: SortableItem): number | null {
  if (!item.published_at) return null;
  const time = Date.parse(item.published_at);
  return Number.isNaN(time) ? null : time;
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
