/** Text for channel suggestions on the discover page. Pure, so server and client agree. */

const compact = new Intl.NumberFormat("en", {
  notation: "compact",
  maximumFractionDigits: 1,
});

/** "2.6M subscribers", or null when YouTube didn't show a count. */
export function formatSubscribers(
  count: number | null | undefined,
): string | null {
  if (count == null || !Number.isFinite(count) || count < 0) return null;
  return `${compact.format(count)} ${count === 1 ? "subscriber" : "subscribers"}`;
}

/**
 * Who features a suggested channel, e.g. "Featured by Veritasium",
 * "Featured by A and B" or "Featured by A, B and 2 others". Names `shown` at most.
 */
export function featuredByText(
  channels: readonly { title: string }[],
  shown = 2,
): string {
  const titles = channels.map((c) => c.title.trim() || "a channel you like");
  if (titles.length === 0) return "Featured by a channel you like";
  if (titles.length === 1) return `Featured by ${titles[0]}`;
  if (titles.length <= shown) {
    return `Featured by ${titles.slice(0, -1).join(", ")} and ${titles.at(-1)}`;
  }
  const rest = titles.length - shown;
  return `Featured by ${titles.slice(0, shown).join(", ")} and ${rest} ${
    rest === 1 ? "other" : "others"
  }`;
}

/** The canonical URL of a channel, for subscribing by URL. */
export function channelUrl(channelId: string): string {
  return `https://www.youtube.com/channel/${channelId}`;
}

const CHANNEL_ID = /^UC[A-Za-z0-9_-]{22}$/;

export function isChannelId(value: string): boolean {
  return CHANNEL_ID.test(value);
}
