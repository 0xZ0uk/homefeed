/** Formatting for video comments. */

const compact = new Intl.NumberFormat("en", {
  notation: "compact",
  maximumFractionDigits: 1,
});

/** "1.2K likes", or null when the count is unknown or zero. */
export function formatLikes(count: number | null | undefined): string | null {
  if (!count) return null;
  return `${compact.format(count)} ${count === 1 ? "like" : "likes"}`;
}
