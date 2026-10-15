/** What the Subscriptions page shows of a subscribed channel's settings. Pure. */

import type { SubscribedChannel } from "@homefeed/api-client";

export type Prior = SubscribedChannel["prior"];
export const PRIORS: readonly Prior[] = [
  "love",
  "like",
  "neutral",
  "skeptical",
];

/**
 * A channel's "preference" as the app words it (the API calls it `prior`):
 * where the channel starts out before your ratings of its videos weigh in.
 */
export const PRIOR_LABELS: Record<Prior, string> = {
  love: "Love",
  like: "Like",
  neutral: "Neutral",
  skeptical: "Skeptical",
};

/** How long a channel is muted for by "Mute for a month". */
export const MONTH_MUTE_DAYS = 30;

/** How a channel is muted: not at all, for good, or until a time that is ahead. */
export type MuteState =
  { kind: "off" } | { kind: "forever" } | { kind: "until"; until: string };

export function muteState(
  channel: Pick<SubscribedChannel, "muted" | "muted_until">,
  now: Date,
): MuteState {
  if (channel.muted) return { kind: "forever" };
  const until = channel.muted_until;
  if (until && Date.parse(until) > now.getTime())
    return { kind: "until", until };
  return { kind: "off" };
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** Whole days left of a trial, counting a started day as a day; 0 once over. */
export function trialDaysLeft(trialUntil: string, now: Date): number {
  const left = Math.ceil((Date.parse(trialUntil) - now.getTime()) / DAY_MS);
  return Number.isNaN(left) ? 0 : Math.max(0, left);
}

/** "Trial · 9 days left", or null for a channel that isn't on trial. */
export function trialLabel(
  trialUntil: string | null | undefined,
  now: Date,
): string | null {
  if (!trialUntil) return null;
  const days = trialDaysLeft(trialUntil, now);
  if (days === 0) return "Trial · ended";
  return `Trial · ${days} ${days === 1 ? "day" : "days"} left`;
}
