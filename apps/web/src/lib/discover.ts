/** Text for channel suggestions on the discover page. Pure, so server and client agree. */

import { TOP_TIER_THRESHOLD } from "#/lib/scores";

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

/** Why a channel that features suggestions counts as one you like. */
export type FeaturedRelation = "love" | "like" | "rated";

const RELATION_TEXT: Record<FeaturedRelation, string> = {
  love: "a channel you love",
  like: "a channel you like",
  rated: `a channel with a video you rated ${TOP_TIER_THRESHOLD} or higher`,
};

/**
 * Who features a suggested channel, e.g. "Featured by Veritasium, a channel
 * you love", "Featured by A and B" or "Featured by A, B and 2 others". Names
 * `shown` at most; a lone channel also says why you like it, when known.
 */
export function featuredByText(
  channels: readonly {
    title: string;
    relation?: FeaturedRelation | null;
  }[],
  shown = 2,
): string {
  const titles = channels.map((c) => c.title.trim() || "a channel you like");
  if (titles.length === 0) return "Featured by a channel you like";
  if (titles.length === 1) {
    const relation = channels[0]?.relation;
    return `Featured by ${titles[0]}${relation ? `, ${RELATION_TEXT[relation]}` : ""}`;
  }
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

/*
 * The two ways to hide a channel, in the words used everywhere. "Not now"
 * (`dismissed`) only skips the channel in Discover; "Hide channel" (`blocked`)
 * also keeps its videos out of your feed.
 */

/** The status-line message after hiding a channel. */
export function hiddenMessage(
  kind: "dismissed" | "blocked",
  title: string,
): string {
  return kind === "dismissed"
    ? `Skipped ${title} in Discover.`
    : `Hid ${title} from your feed and Discover.`;
}

/** Label for a hidden channel in Settings. */
export function hideKindLabel(kind: "dismissed" | "blocked"): string {
  return kind === "dismissed"
    ? "Skipped in Discover"
    : "Hidden from feed and Discover";
}
