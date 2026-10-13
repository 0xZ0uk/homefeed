/** Display helpers for topic boosts. Pure, so server and client render the same text. */

import { formatAge } from "#/lib/format";

/** Slider step for topic weights. */
export const WEIGHT_STEP = 0.05;
/** With decay on, a topic's weight halves every this many days unless reaffirmed. */
export const HALF_LIFE_DAYS = 30;

/** `value` rounded to the slider step and clamped to [-1, 1]. */
export function clampWeight(value: number): number {
  if (!Number.isFinite(value)) return 0;
  const stepped = Math.round(value / WEIGHT_STEP) * WEIGHT_STEP;
  // toFixed drops float noise (0.15000000000000002); `|| 0` turns -0 into 0.
  return Math.min(1, Math.max(-1, Number(stepped.toFixed(2)))) || 0;
}

/** A weight with its sign, e.g. "+0.50", "−0.25" or "0.00". */
export function formatWeight(weight: number): string {
  const fixed = Math.abs(weight).toFixed(2);
  if (fixed === "0.00") return fixed;
  return `${weight > 0 ? "+" : "−"}${fixed}`;
}

/** What a weight does to matching videos. */
export function weightEffect(weight: number): string {
  if (formatWeight(weight) === "0.00") return "No effect";
  return weight > 0 ? "Boost" : "Suppress";
}

/**
 * For a decaying topic, its current weight and when it was last reaffirmed,
 * e.g. "Now +0.40, reaffirmed 1 month ago".
 */
export function decayNote(
  topic: { effective_weight: number; reaffirmed_at: string },
  now: Date = new Date(),
): string {
  const age = formatAge(topic.reaffirmed_at, now);
  const current = `Now ${formatWeight(topic.effective_weight)}`;
  return age ? `${current}, reaffirmed ${age}` : current;
}

/** How a topic matches videos. */
export type MatchMode = "embedding" | "tag" | "both";

export const MATCH_MODES: readonly MatchMode[] = ["embedding", "tag", "both"];

/** A match mode's name in the Topics tab. */
export function matchModeLabel(mode: MatchMode): string {
  return {
    embedding: "Similar videos",
    tag: "Tagged videos",
    both: "Similar or tagged",
  }[mode];
}

/** A subscribed tag, for the sidebar. */
export interface SubscribedTag {
  slug: string;
  label: string;
}

/**
 * The tags the user has subscribed to with a positive weight (a tag given a
 * zero or negative weight is muted, not followed), alphabetically.
 */
export function subscribedTags(
  topics: ReadonlyArray<{
    weight: number;
    tag_slug?: string | null;
    tag_label?: string | null;
  }>,
): SubscribedTag[] {
  return topics
    .flatMap((topic) =>
      topic.tag_slug && topic.weight > 0
        ? [{ slug: topic.tag_slug, label: topic.tag_label ?? topic.tag_slug }]
        : [],
    )
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** Whether a topic suppresses its videos (a negative weight): a muted tag when
 * the topic is backed by one. */
export function isMuted(topic: { weight: number }): boolean {
  return topic.weight < 0;
}

/** The weight at which a muted tag can hide its videos from the feed. */
export const HIDE_WEIGHT = -1;

/** The tags the user has muted (a negative weight), alphabetically. */
export function mutedTags(
  topics: ReadonlyArray<{
    weight: number;
    tag_slug?: string | null;
    tag_label?: string | null;
  }>,
): SubscribedTag[] {
  return topics
    .flatMap((topic) =>
      topic.tag_slug && isMuted(topic)
        ? [{ slug: topic.tag_slug, label: topic.tag_label ?? topic.tag_slug }]
        : [],
    )
    .sort((a, b) => a.label.localeCompare(b.label));
}
