/**
 * The 1 to 10 rating scale (PLAN.md section 3). Scores are the whole numbers
 * the API stores, 1 to 10. The app shows them as faces from a wail (1) to a
 * grin (10), each with a word.
 */

export const MIN_SCORE = 1;
export const MAX_SCORE = 10;

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
