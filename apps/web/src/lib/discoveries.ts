import type {
  DiscoveredChannelOut,
  DiscoveryRecapOut,
  DiscoveryWindowOut,
} from "@homefeed/api-client";

import { trialDaysLeft } from "#/lib/channels";
import { hideKindLabel } from "#/lib/discover";
import { deltaPoints, formatDay, formatPercent, plural } from "#/lib/insights";
import { scoreText } from "#/lib/scores";

/**
 * Pure helpers for the Insights page's discovery recap: the sentences, the
 * figures set against the week before, and how a channel is described. The
 * numbers come from the API; this is only how they are worded and compared.
 */

/** Two dates as a range: "Oct 9–15", "Sep 28 – Oct 4", or "Oct 9" for one day. */
export function formatDateRange(start: string, end: string): string {
  if (start === end) return formatDay(start);
  const first = new Date(`${start}T00:00:00Z`);
  const last = new Date(`${end}T00:00:00Z`);
  if (Number.isNaN(first.getTime()) || Number.isNaN(last.getTime())) {
    return `${start} – ${end}`;
  }
  const sameMonth =
    first.getUTCFullYear() === last.getUTCFullYear() &&
    first.getUTCMonth() === last.getUTCMonth();
  return sameMonth
    ? `${formatDay(start)}–${last.getUTCDate()}`
    : `${formatDay(start)} – ${formatDay(end)}`;
}

/**
 * What the two windows are called in a sentence: "this week" and "last week"
 * for a week, otherwise by their length. `versus` is the earlier one after
 * "compared with".
 */
export function periodWords(days: number): {
  current: string;
  previous: string;
  versus: string;
} {
  if (days === 7) {
    return { current: "this week", previous: "last week", versus: "last week" };
  }
  if (days === 1) {
    return { current: "today", previous: "yesterday", versus: "yesterday" };
  }
  return {
    current: `in the last ${days} days`,
    previous: `in the ${days} days before`,
    versus: `the ${days} days before`,
  };
}

/** Which days the recap covers, e.g. "The last 7 days (Oct 9–15), compared with…". */
export function recapPeriod(recap: DiscoveryRecapOut): string {
  const { current, previous, days } = recap;
  const span = plural(days, "day");
  return `The last ${span} (${formatDateRange(current.start, current.end)}), compared with the ${span} before (${formatDateRange(previous.start, previous.end)}).`;
}

/** What became of the channels tried, in the headline's last words. */
function keptClause({
  new_channels: tried,
  kept_channels: kept,
}: DiscoveryWindowOut): string {
  if (kept === 0)
    return tried === 1 ? "haven't kept it yet" : "haven't kept any yet";
  if (kept < tried) return `kept ${kept}`;
  if (tried === 1) return "kept it";
  return tried === 2 ? "kept both" : "kept all of them";
}

/**
 * The recap in a sentence, e.g. "You tried 4 new channels this week (2 last
 * week) and kept 1."
 */
export function recapHeadline(recap: DiscoveryRecapOut): string {
  const { current, previous } = recap;
  const words = periodWords(recap.days);
  if (current.new_channels === 0) {
    return previous.new_channels === 0
      ? `You didn't try any new channels ${words.current} or ${words.previous}.`
      : `You didn't try any new channels ${words.current} (${previous.new_channels} ${words.previous}).`;
  }
  return `You tried ${plural(current.new_channels, "new channel")} ${words.current} (${previous.new_channels} ${words.previous}) and ${keptClause(current)}.`;
}

/** How a figure moved since the window before, as the chip beside it says. */
export interface Change {
  direction: "up" | "down" | "same";
  /** "+2", "−1" or "No change", in points for a share: "+6 pts". */
  label: string;
}

/**
 * A count against the one before it; null when both are zero, as there is
 * nothing to compare.
 */
export function countChange(current: number, previous: number): Change | null {
  if (current === 0 && previous === 0) return null;
  const difference = current - previous;
  if (difference === 0) return { direction: "same", label: "No change" };
  return {
    direction: difference > 0 ? "up" : "down",
    label: `${difference > 0 ? "+" : "−"}${Math.abs(difference)}`,
  };
}

/**
 * A share against the one before it in whole percentage points; null when
 * either is unknown, as nothing was watched in that window.
 */
export function shareChange(
  current: number | null,
  previous: number | null,
): Change | null {
  const points = deltaPoints(current, previous);
  if (points === null) return null;
  if (points === 0) return { direction: "same", label: "No change" };
  return {
    direction: points > 0 ? "up" : "down",
    label: `${points > 0 ? "+" : "−"}${Math.abs(points)} pts`,
  };
}

/** One of the totals, with the window before beside it. */
export interface RecapStat {
  key: "tried" | "kept" | "liked" | "share";
  label: string;
  value: string;
  /** The window before, e.g. "2 last week". */
  detail: string;
  change: Change | null;
}

/**
 * The totals the recap shows, each with the window before beside it: channels
 * tried, kept, and rated top tier, and the share of watched videos that came
 * from new channels.
 */
export function recapStats(recap: DiscoveryRecapOut): RecapStat[] {
  const { current, previous } = recap;
  const { previous: before } = periodWords(recap.days);
  const count = (
    key: RecapStat["key"],
    label: string,
    pick: (window: DiscoveryWindowOut) => number,
  ): RecapStat => ({
    key,
    label,
    value: String(pick(current)),
    detail: `${pick(previous)} ${before}`,
    change: countChange(pick(current), pick(previous)),
  });
  return [
    count("tried", "New channels tried", (w) => w.new_channels),
    count("kept", "Channels kept", (w) => w.kept_channels),
    count(
      "liked",
      `Channels rated ${recap.top_tier_threshold} or higher`,
      (w) => w.liked_channels,
    ),
    {
      key: "share",
      label: "Videos from new channels",
      value: formatPercent(current.new_channel_share),
      detail: shareDetail(current, previous, before),
      change: shareChange(
        current.new_channel_share,
        previous.new_channel_share,
      ),
    },
  ];
}

function shareDetail(
  current: DiscoveryWindowOut,
  previous: DiscoveryWindowOut,
  before: string,
): string {
  const now =
    current.videos_watched === 0
      ? "No videos watched"
      : `${current.new_channel_videos} of ${plural(current.videos_watched, "video")}`;
  if (previous.new_channel_share === null) {
    return current.videos_watched === 0 ? now : `${now} · no videos ${before}`;
  }
  return `${now} · ${formatPercent(previous.new_channel_share)} ${before}`;
}

/** The sentence that says what "tried" and "kept" count. */
export const RECAP_NOTE =
  "A channel counts as tried when you first watch one of its videos, and as kept while you subscribe to it or have it on a trial.";

/**
 * Where a channel stands, in words: "Subscribed", "On trial · 12 days left",
 * "Hidden" or "Not followed".
 */
export function channelStatusLabel(
  channel: Pick<DiscoveredChannelOut, "status" | "trial_until">,
  now: Date,
): string {
  switch (channel.status) {
    case "subscribed":
      return "Subscribed";
    case "trial": {
      const days = channel.trial_until
        ? trialDaysLeft(channel.trial_until, now)
        : 0;
      return days === 0
        ? "On trial · ends today"
        : `On trial · ${plural(days, "day")} left`;
    }
    case "hidden":
      return "Hidden";
    case "not_followed":
      return "Not followed";
  }
}

/** Whether the channel is one I follow: subscribed to, a trial included. */
export function isFollowed(channel: Pick<DiscoveredChannelOut, "status">) {
  return channel.status === "subscribed" || channel.status === "trial";
}

/**
 * What I did with a new channel: "3 videos watched · average rating 8.5 from 2
 * ratings", "1 video watched · rated 9" or "2 videos watched · not rated".
 */
export function describeChannel(
  channel: Pick<
    DiscoveredChannelOut,
    "videos_watched" | "rating_count" | "average_score"
  >,
): string {
  const watched = `${plural(channel.videos_watched, "video")} watched`;
  const { rating_count: count, average_score: average } = channel;
  if (count === 0 || average === null) return `${watched} · not rated`;
  if (count === 1) return `${watched} · rated ${average}`;
  return `${watched} · average rating ${average.toFixed(1)} from ${count} ratings`;
}

/** The channels worth following up, in the order given. */
export function followUps<T extends Pick<DiscoveredChannelOut, "follow_up">>(
  channels: readonly T[],
): T[] {
  return channels.filter((channel) => channel.follow_up);
}

/**
 * Why a channel is worth following, e.g. "Best rating: Excellent, 9 out of
 * 10", and what stands in the way for a channel I had hidden, e.g. "Hidden
 * from feed and Discover": subscribing shows it again.
 */
export function followUpReason(
  channel: Pick<DiscoveredChannelOut, "top_score" | "hide_kind">,
): string | null {
  const parts = [
    channel.top_score === null
      ? null
      : `Best rating: ${scoreText(channel.top_score)}`,
    channel.hide_kind ? hideKindLabel(channel.hide_kind) : null,
  ].filter((part) => part !== null);
  return parts.length === 0 ? null : parts.join(" · ");
}

/** What the status line says after subscribing from a follow-up. */
export function subscribedMessage(title: string, created: boolean): string {
  return created
    ? `Subscribed to ${title}.`
    : `You're already subscribed to ${title}.`;
}

/** What the status line says after starting a trial from a follow-up. */
export function trialStartedMessage(title: string, created: boolean): string {
  return created
    ? `Started a 2-week trial of ${title}. You decide in Subscriptions whether to keep it.`
    : `You're already subscribed to ${title}.`;
}

/** What the status line says after undoing either. */
export function unsubscribedMessage(title: string): string {
  return `Unsubscribed from ${title}.`;
}

/**
 * Which new topics are shown out of how many there are, or null when all of
 * them are: "Showing the 12 most watched of 15."
 */
export function topicsNote(shown: number, total: number): string | null {
  return shown < total
    ? `Showing the ${shown} most watched of ${total}.`
    : null;
}
