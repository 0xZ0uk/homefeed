/** Display helpers for tag subscriptions (subscribed and muted tags). Pure, so
 * server and client render the same text. */

/** Slider step for tag weights. */
export const WEIGHT_STEP = 0.05;

/** The weight at which a muted tag can hide its videos from the feed. */
export const HIDE_WEIGHT = -1;

/** What the lists need of a subscription. */
export interface Subscription {
  slug: string;
  label: string;
  weight: number;
}

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

/** What a weight does to videos carrying the tag. */
export function weightEffect(weight: number): string {
  if (formatWeight(weight) === "0.00") return "No effect";
  return weight > 0 ? "Boost" : "Suppress";
}

/** Whether a subscription suppresses its tag's videos (a negative weight). */
export function isMuted(subscription: { weight: number }): boolean {
  return subscription.weight < 0;
}

/** A tag as the Explore page lists it. */
export interface SidebarTag {
  slug: string;
  label: string;
}

function sidebarTags(
  subscriptions: readonly Subscription[],
  keep: (weight: number) => boolean,
): SidebarTag[] {
  return subscriptions
    .filter((s) => keep(s.weight))
    .map(({ slug, label }) => ({ slug, label }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/**
 * The tags the user follows: a positive weight (a tag given a zero or negative
 * weight is not followed), alphabetically.
 */
export function subscribedTags(
  subscriptions: readonly Subscription[],
): SidebarTag[] {
  return sidebarTags(subscriptions, (weight) => weight > 0);
}

/** The tags the user has muted (a negative weight), alphabetically. */
export function mutedTags(
  subscriptions: readonly Subscription[],
): SidebarTag[] {
  return sidebarTags(subscriptions, (weight) => weight < 0);
}

/** The weight of each subscription with a non-zero weight, by tag slug. */
export function tagWeights(
  subscriptions: ReadonlyArray<{ slug: string; weight: number }>,
): Map<string, number> {
  const weights = new Map<string, number>();
  for (const { slug, weight } of subscriptions) {
    if (formatWeight(weight) !== "0.00") weights.set(slug, weight);
  }
  return weights;
}

/** A tag's state in the Tags list. */
export type TagState = "subscribed" | "muted" | "none";

/** Subscribed with a weight of 0 or more (it shows as subscribed, and
 * Unsubscribe removes it); muted below 0. */
export function tagState(
  subscription: { weight: number } | undefined,
): TagState {
  if (!subscription) return "none";
  return isMuted(subscription) ? "muted" : "subscribed";
}

/** Which tags the Tags list shows (filtered by the API). */
export type TagFilter = "all" | "subscribed" | "muted";

export const TAG_FILTERS: ReadonlyArray<{ id: TagFilter; label: string }> = [
  { id: "all", label: "All" },
  { id: "subscribed", label: "Subscribed" },
  { id: "muted", label: "Muted" },
];
