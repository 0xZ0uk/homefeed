/**
 * How subscribed channels are doing, for pruning the ones that keep landing in
 * the feed without being watched: the row text, the sort, and which channels to
 * suggest letting go. Pure.
 */

import type { ChannelHealthOut } from "@homefeed/api-client";

import { muteState } from "#/lib/channels";
import { formatAge } from "#/lib/format";

export type ChannelHealth = ChannelHealthOut;

/** How many days of feeds count as picks; the API's default window. */
export const PICKS_WINDOW_DAYS = 30;

/** A channel with this many picks in the window and none watched keeps showing up. */
export const DORMANT_MIN_PICKS = 5;

/**
 * "Watched 2 of 14 picks · avg 6.5 from 4 ratings · last watched 3 weeks
 * ago". Null until the channel's numbers have loaded.
 */
export function describeHealth(
  health: ChannelHealth | undefined,
  now: Date,
): string | null {
  if (!health) return null;
  const { picks, watched_picks, rating_count, average_score } = health;
  const age = formatAge(health.last_watched_at, now);
  return [
    picks > 0
      ? `Watched ${watched_picks} of ${picks} ${picks === 1 ? "pick" : "picks"}`
      : `No picks in the last ${PICKS_WINDOW_DAYS} days`,
    rating_count > 0 && average_score !== null
      ? `avg ${average_score.toFixed(1)} from ${rating_count} ${rating_count === 1 ? "rating" : "ratings"}`
      : "no ratings yet",
    age ? `last watched ${age}` : "never watched",
  ].join(" · ");
}

export const CHANNEL_SORTS = [
  { value: "title", label: "A–Z" },
  { value: "least-watched", label: "Least watched" },
  { value: "most-picks", label: "Most picks" },
] as const;
export type ChannelSort = (typeof CHANNEL_SORTS)[number]["value"];

export function isChannelSort(value: unknown): value is ChannelSort {
  return CHANNEL_SORTS.some((sort) => sort.value === value);
}

interface Sortable {
  channel_id: string;
  title: string;
}

function byTitle(a: Sortable, b: Sortable): number {
  return (
    a.title.localeCompare(b.title, "en", { sensitivity: "base" }) ||
    a.channel_id.localeCompare(b.channel_id)
  );
}

function lastWatched(health: ChannelHealth | undefined): number {
  const at = health?.last_watched_at ? Date.parse(health.last_watched_at) : NaN;
  return Number.isNaN(at) ? -Infinity : at;
}

/**
 * The channels in `sort` order, as a new list:
 * - A–Z: by title.
 * - Least watched: channels with picks lately first, the smaller the share of
 *   them watched the earlier (more picks first among equals); then channels
 *   without picks, the longest unwatched (or never watched) first.
 * - Most picks: the most picks in the window first.
 * Ties go by title. Without `health` every sort is A–Z.
 */
export function sortChannels<T extends Sortable>(
  channels: readonly T[],
  health: ReadonlyMap<string, ChannelHealth> | undefined,
  sort: ChannelSort,
): T[] {
  const sorted = [...channels];
  if (!health || sort === "title") return sorted.sort(byTitle);
  const picks = (channel: T) => health.get(channel.channel_id)?.picks ?? 0;
  if (sort === "most-picks") {
    return sorted.sort((a, b) => picks(b) - picks(a) || byTitle(a, b));
  }
  const watchedShare = (channel: T) =>
    (health.get(channel.channel_id)?.watched_picks ?? 0) / picks(channel);
  return sorted.sort((a, b) => {
    const [pa, pb] = [picks(a), picks(b)];
    if (pa > 0 !== pb > 0) return pa > 0 ? -1 : 1;
    if (pa > 0) {
      return watchedShare(a) - watchedShare(b) || pb - pa || byTitle(a, b);
    }
    const [la, lb] = [
      lastWatched(health.get(a.channel_id)),
      lastWatched(health.get(b.channel_id)),
    ];
    return (la === lb ? 0 : la < lb ? -1 : 1) || byTitle(a, b);
  });
}

/**
 * The channels that keep showing up but are never watched: `DORMANT_MIN_PICKS`
 * or more picks in the window and none of them watched. Channels that are
 * muted or on trial are left out, since they are being dealt with. Most picks
 * first.
 */
export function dormantChannels<
  T extends Sortable & {
    muted: boolean;
    muted_until: string | null;
    trial_until: string | null;
  },
>(
  channels: readonly T[],
  health: ReadonlyMap<string, ChannelHealth> | undefined,
  now: Date,
): T[] {
  if (!health) return [];
  const picks = (channel: T) => health.get(channel.channel_id)?.picks ?? 0;
  return channels
    .filter((channel) => {
      const stats = health.get(channel.channel_id);
      return (
        stats !== undefined &&
        stats.picks >= DORMANT_MIN_PICKS &&
        stats.watched_picks === 0 &&
        !channel.trial_until &&
        muteState(channel, now).kind === "off"
      );
    })
    .sort((a, b) => picks(b) - picks(a) || byTitle(a, b));
}

/** Where the browser remembers which channels the prune panel was dismissed for. */
export const PRUNE_DISMISSED_KEY = "homefeed:prune-dismissed";

/** The channel ids saved as dismissed; anything unreadable is nothing. */
export function parseDismissed(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((id): id is string => typeof id === "string")
      : [];
  } catch {
    return [];
  }
}

/** The channels whose id isn't in `dismissed`. */
export function withoutDismissed<T extends { channel_id: string }>(
  channels: readonly T[],
  dismissed: readonly string[],
): T[] {
  return channels.filter((channel) => !dismissed.includes(channel.channel_id));
}
