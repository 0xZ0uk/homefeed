/**
 * The mix of a feed: which topics its picks are about, and the dial that sets
 * how adventurous the next feed is. Pure, so the counting, the presets and
 * what they say are easy to test.
 */

import type { Parsed } from "#/lib/settings";

/** How many topics the strip under Today's header names. */
export const MIX_TOPICS = 5;

/** What the strip needs of a pick: its topic tags. */
export interface TaggedPick {
  tags?: readonly { slug: string; label: string }[];
}

export interface TopicCount {
  slug: string;
  label: string;
  /** How many of the picks carry the tag. */
  count: number;
}

/**
 * Every topic of `picks` with how many picks carry it: the most first, ties
 * alphabetically. A tag counts once per pick, and a pick without tags counts
 * for nothing.
 */
export function topicCounts(picks: readonly TaggedPick[]): TopicCount[] {
  const topics = new Map<string, TopicCount>();
  for (const pick of picks) {
    const counted = new Set<string>();
    for (const { slug, label } of pick.tags ?? []) {
      if (counted.has(slug)) continue;
      counted.add(slug);
      const topic = topics.get(slug);
      if (topic) topic.count += 1;
      else topics.set(slug, { slug, label, count: 1 });
    }
  }
  return [...topics.values()].sort(
    (a, b) =>
      b.count - a.count ||
      a.label.localeCompare(b.label) ||
      a.slug.localeCompare(b.slug),
  );
}

/** The `limit` topics most of `picks` are about (see `topicCounts`). */
export function topTopics(
  picks: readonly TaggedPick[],
  limit: number = MIX_TOPICS,
): TopicCount[] {
  return topicCounts(picks).slice(0, Math.max(0, limit));
}

/** What the sliders need of a tag subscription. */
export interface FollowedTag {
  slug: string;
  label: string;
  weight: number;
}

/**
 * The tags I follow (a positive weight) for the sliders: those with the most
 * picks today first, then the rest alphabetically. `counts` holds each tag's
 * picks by slug (see `topicCounts`).
 */
export function followedTags<T extends FollowedTag>(
  subscriptions: readonly T[],
  counts: ReadonlyMap<string, number>,
): T[] {
  return subscriptions
    .filter(({ weight }) => weight > 0)
    .sort(
      (a, b) =>
        (counts.get(b.slug) ?? 0) - (counts.get(a.slug) ?? 0) ||
        a.label.localeCompare(b.label),
    );
}

/** The dial's three choices. */
export type MixPreset = "familiar" | "balanced" | "adventurous";

export interface MixChoice {
  value: MixPreset;
  label: string;
  /** Discovery slots, before they're held to the size of the feed. */
  slots: number;
  /** The most of the feed one followed topic may take, 0 to 1. */
  share: number;
}

/** Familiar to Adventurous: more discovery slots and less room for one topic. */
export const MIX_PRESETS: readonly MixChoice[] = [
  { value: "familiar", label: "Familiar", slots: 1, share: 0.6 },
  { value: "balanced", label: "Balanced", slots: 3, share: 0.4 },
  { value: "adventurous", label: "Adventurous", slots: 6, share: 0.25 },
];

export function isMixPreset(value: unknown): value is MixPreset {
  return MIX_PRESETS.some((preset) => preset.value === value);
}

/** The settings the dial reads and writes. */
export interface MixValues {
  feed_size: number;
  feed_exploration_slots: number;
  feed_max_topic_share: number;
}

/**
 * The settings a preset stands for in a feed of `feedSize` videos: its
 * discovery slots, kept to the size of the feed, and its share.
 */
export function mixSettings(
  preset: MixPreset,
  feedSize: number,
): Pick<MixValues, "feed_exploration_slots" | "feed_max_topic_share"> {
  const choice = MIX_PRESETS.find(({ value }) => value === preset);
  if (!choice) throw new Error(`Unknown mix: ${preset}`);
  return {
    feed_exploration_slots: Math.min(choice.slots, Math.max(0, feedSize)),
    feed_max_topic_share: choice.share,
  };
}

/** Shares closer than this are the same: the API stores what was sent. */
const SHARE_TOLERANCE = 0.005;

/** The preset `values` are, or "custom" when they match none. */
export function currentMix(values: MixValues): MixPreset | "custom" {
  for (const { value } of MIX_PRESETS) {
    const preset = mixSettings(value, values.feed_size);
    if (
      preset.feed_exploration_slots === values.feed_exploration_slots &&
      Math.abs(preset.feed_max_topic_share - values.feed_max_topic_share) <
        SHARE_TOLERANCE
    ) {
      return value;
    }
  }
  return "custom";
}

/**
 * The discovery slots and the share of the feed one topic may take that
 * `choice` stands for: a preset's, in a feed of `values.feed_size`, or the
 * `values` themselves for a custom mix.
 */
export function mixOf(
  choice: MixPreset | "custom",
  values: MixValues,
): { slots: number; share: number } {
  if (choice === "custom") {
    return {
      slots: values.feed_exploration_slots,
      share: values.feed_max_topic_share,
    };
  }
  const preset = mixSettings(choice, values.feed_size);
  return {
    slots: preset.feed_exploration_slots,
    share: preset.feed_max_topic_share,
  };
}

/** A share of the feed as a percentage: 0.4 is "40%". */
export function formatShare(share: number): string {
  return `${Math.round(share * 100)}%`;
}

/** The mix's name as the strip shows it: "Balanced", or "Custom". */
export function mixLabel(mix: MixPreset | "custom"): string {
  return MIX_PRESETS.find(({ value }) => value === mix)?.label ?? "Custom";
}

/** What a mix does, in words: its discovery slots and how much one topic may take. */
export function describeMix(slots: number, share: number): string {
  const picks = `${slots} ${slots === 1 ? "discovery slot" : "discovery slots"}`;
  return share >= 1
    ? `${picks}, and no limit on how much one topic takes.`
    : `${picks}, and no topic takes more than ${formatShare(share)} of the feed.`;
}

/** The lowest and highest share the settings accept, as percentages. */
export const MIN_SHARE_PERCENT = 10;
export const MAX_SHARE_PERCENT = 100;

/**
 * The share of the feed one topic may take from a form field in percent: a
 * whole number from 10 to 100, as a share from 0.1 to 1.
 */
export function parseSharePercent(raw: string, label: string): Parsed<number> {
  const text = raw.trim();
  const percent = Number(text);
  if (
    text === "" ||
    !Number.isInteger(percent) ||
    percent < MIN_SHARE_PERCENT ||
    percent > MAX_SHARE_PERCENT
  ) {
    return {
      ok: false,
      message: `${label} must be a whole number from ${MIN_SHARE_PERCENT} to ${MAX_SHARE_PERCENT}.`,
    };
  }
  return { ok: true, value: percent / 100 };
}

/** A share for a form field in percent: 0.4 is "40". */
export function sharePercentText(share: number): string {
  return String(Math.round(share * 100));
}
