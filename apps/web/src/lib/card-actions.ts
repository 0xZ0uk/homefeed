/**
 * The pure parts of the quick actions on a video card (rate it, queue it for
 * later): what its status line says and how the videos on screen change. The
 * status line itself is in `ActionStatus`.
 */

import { scoreText } from "#/lib/scores";

/** What the status line under the feed's chips shows after an action. */
export interface ActionStatus {
  /** Whether it worked; a failure is shown as an error. */
  ok: boolean;
  message: string;
  /** Undoes the action; the status line then offers an "Undo" button. */
  undo?: () => void;
  /** Move focus to the status line, e.g. because the control used is gone. */
  focus?: boolean;
}

/**
 * `items` with the rating of the video `videoId` set (null clears it). Returns
 * `items` itself when none of them is that video, and keeps the other items as
 * they are.
 */
export function withRating<
  T extends { video_id: string; rating: number | null },
>(items: T[], videoId: string, score: number | null): T[] {
  if (!items.some((item) => item.video_id === videoId)) return items;
  return items.map((item) =>
    item.video_id === videoId ? { ...item, rating: score } : item,
  );
}

/** What the status line says once a video was rated from its card. */
export function ratedMessage(title: string, score: number): string {
  return `Rated “${title}”: ${scoreText(score)}.`;
}

/** What the status line says once a video was queued, or taken off the queue. */
export function queuedMessage(title: string, added: boolean): string {
  return added
    ? `Added “${title}” to your queue.`
    : `Removed “${title}” from your queue.`;
}

/** What the status line says once an action was undone. */
export const UNDONE_MESSAGE = "Undone.";
