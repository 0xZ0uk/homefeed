/**
 * "More like this" and "Less like this": the signals a card sends and how the
 * videos on screen change when one is given. Pure, so server and client agree
 * and the toggling is easy to test.
 */

/** 1 is "more like this", -1 is "less like this". */
export type Signal = 1 | -1;

export const MORE_LIKE_THIS: Signal = 1;
export const LESS_LIKE_THIS: Signal = -1;

export function isSignal(value: unknown): value is Signal {
  return value === MORE_LIKE_THIS || value === LESS_LIKE_THIS;
}

/** A video's `feedback` from the API (a plain number or null) as a signal. */
export function signalOf(feedback: number | null | undefined): Signal | null {
  return isSignal(feedback) ? feedback : null;
}

/**
 * The signal a video is left with when `pressed` is pressed: the one it
 * already has is cleared, any other replaces what it had.
 */
export function nextSignal(
  current: Signal | null,
  pressed: Signal,
): Signal | null {
  return current === pressed ? null : pressed;
}

/**
 * `items` with the feedback of the video `videoId` set (null clears it).
 * Returns `items` itself when none of them is that video, and keeps the other
 * items as they are.
 */
export function withFeedback<
  T extends { video_id: string; feedback: number | null },
>(items: T[], videoId: string, signal: Signal | null): T[] {
  if (!items.some((item) => item.video_id === videoId)) return items;
  return items.map((item) =>
    item.video_id === videoId ? { ...item, feedback: signal } : item,
  );
}

/** What the status line says once a video's feedback went from `before` to `after`. */
export function feedbackMessage(
  title: string,
  after: Signal | null,
  before: Signal | null,
): string {
  if (after === MORE_LIKE_THIS) return `Marked “${title}” as more like this.`;
  if (after === LESS_LIKE_THIS) return `Marked “${title}” as less like this.`;
  const was = before === MORE_LIKE_THIS ? "more like this" : "less like this";
  return `Cleared “${was}” on “${title}”.`;
}
