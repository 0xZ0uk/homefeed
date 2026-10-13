/**
 * The 1 to 10 rating scale (PLAN.md section 3). Scores are the numbers the
 * API stores, from 1.0 to 10.0 with one decimal, e.g. 7.4.
 */

export const MIN_SCORE = 1;
export const MAX_SCORE = 10;

/** A score between 1 and 10 with at most one decimal. */
export function isScore(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= MIN_SCORE &&
    value <= MAX_SCORE &&
    Math.abs(value * 10 - Math.round(value * 10)) < 1e-9
  );
}

/** A score with its one decimal, e.g. "7.0" or "9.9". */
export function formatScore(score: number): string {
  return score.toFixed(1);
}
