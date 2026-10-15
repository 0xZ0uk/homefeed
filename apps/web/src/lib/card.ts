/**
 * What a video card says to help decide whether to watch the video: its length
 * in words, the flags its LLM scores earn, how far through it I got and what
 * the card says about its state. Pure, so the thresholds are easy to test.
 */

/** A video this deep (0 to 1) is a "Deep dive". */
export const DEEP_DIVE_DEPTH = 0.7;
/** A video this clickbait-y (0 to 1) is "Likely clickbait". */
export const CLICKBAIT_SCORE = 0.6;

export type CardFlag = "deep-dive" | "clickbait";

/** The words of each flag; a card always shows them with an icon. */
export const CARD_FLAG_LABELS: Record<CardFlag, string> = {
  "deep-dive": "Deep dive",
  clickbait: "Likely clickbait",
};

/** The LLM scores the flags read. */
export interface LlmScores {
  depth: number;
  clickbait: number;
}

/**
 * The flags `llm` earns, in the order a card shows them. A video can earn
 * both (a long one with a baiting title); one that isn't tagged yet earns none.
 */
export function cardFlags(llm: LlmScores | null | undefined): CardFlag[] {
  const flags: CardFlag[] = [];
  if (!llm) return flags;
  if (llm.depth >= DEEP_DIVE_DEPTH) flags.push("deep-dive");
  if (llm.clickbait >= CLICKBAIT_SCORE) flags.push("clickbait");
  return flags;
}

/**
 * A video's length in words, rounded to the minute: "6 min", "1 h 9 min",
 * "2 h". Null when the length is unknown (RSS-only videos).
 */
export function formatLength(
  seconds: number | null | undefined,
): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null;
  const minutes = Math.round(seconds / 60);
  if (minutes < 1) return "under 1 min";
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${rest} min`;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

/**
 * How much of a progress bar to fill for `fraction` (0 to 1), as a whole
 * percentage. Null when there's nothing to show: no progress known, or less
 * than half a percent of it.
 */
export function progressPercent(
  fraction: number | null | undefined,
): number | null {
  if (fraction == null || !Number.isFinite(fraction)) return null;
  const percent = Math.round(Math.min(1, Math.max(0, fraction)) * 100);
  return percent > 0 ? percent : null;
}

/** What a dismissed card says: "Dismissed", and why when it has a reason. */
export function dismissedLabel(reason: string | null | undefined): string {
  const why = reason?.trim();
  return why ? `Dismissed: ${why}` : "Dismissed";
}

/** What a card says about a rating I gave. */
export function ratedLabel(score: number): string {
  return `You rated it ${score}`;
}
