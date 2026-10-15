/**
 * The 1 to 10 rating scale (PLAN.md section 3). Scores are the whole numbers
 * the API stores, 1 to 10. The app shows them as faces from a wail (1) to a
 * grin (10), each with a word.
 */

export const MIN_SCORE = 1;
export const MAX_SCORE = 10;

/**
 * From this score up a rating is top tier, as the API counts it: videos rated
 * this high make their channels ones you like, whose featured channels Discover
 * suggests.
 */
export const TOP_TIER_THRESHOLD = 7;

/** Every score, worst first. */
export const SCORES: readonly number[] = Array.from(
  { length: MAX_SCORE - MIN_SCORE + 1 },
  (_, index) => MIN_SCORE + index,
);

const LABELS = [
  "Awful",
  "Very bad",
  "Bad",
  "Poor",
  "Meh",
  "Okay",
  "Good",
  "Great",
  "Excellent",
  "Amazing",
] as const;

/** A whole score between 1 and 10. */
export function isScore(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isInteger(value) &&
    value >= MIN_SCORE &&
    value <= MAX_SCORE
  );
}

/** The score's word, e.g. "Great" for 8. */
export function scoreLabel(score: number): string {
  return LABELS[score - MIN_SCORE] ?? String(score);
}

/** The score for screen readers and tooltips, e.g. "Great, 8 out of 10". */
export function scoreText(score: number): string {
  return `${scoreLabel(score)}, ${score} out of 10`;
}

/**
 * What the two ends of the scale mean, in the scale's own words, e.g.
 * "1 = awful · 10 = amazing": the hint shown beside the faces, which are only
 * named in tooltips otherwise.
 */
export const SCORE_SCALE_HINT = `${MIN_SCORE} = ${scoreLabel(MIN_SCORE).toLowerCase()} · ${MAX_SCORE} = ${scoreLabel(MAX_SCORE).toLowerCase()}`;
