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
