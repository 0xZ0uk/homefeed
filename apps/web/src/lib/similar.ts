/**
 * The watch page's "More like this": what it shows and says at each step.
 * Nothing similar is looked up until the button is pressed. Pure.
 */

/** The one line that says these appear only on request. */
export const SIMILAR_NOTE = "Similar videos only appear when you ask for them.";

/** When the videos are there but none is like this one yet. */
export const SIMILAR_EMPTY =
  "Nothing similar yet. Similar videos show up once videos are analysed.";

/** When they couldn't be loaded; the button beside it tries again. */
export const SIMILAR_FAILED =
  "Couldn't load similar videos. Try again in a moment.";

/** Where the request is: before it, under way, and how it ended. */
export type SimilarView = "idle" | "loading" | "failed" | "empty" | "found";

/**
 * Which step to show. `count` is how many videos came back, null while there
 * is no answer; an answer already held wins over a later failure to refresh it.
 */
export function similarView(
  asked: boolean,
  result: { count: number | null; failed: boolean },
): SimilarView {
  if (!asked) return "idle";
  if (result.count !== null) return result.count === 0 ? "empty" : "found";
  return result.failed ? "failed" : "loading";
}

/** The button's label: it asks, then waits, then (after a failure) asks again. */
export function similarButtonLabel(view: SimilarView): string {
  if (view === "loading") return "Finding…";
  if (view === "failed") return "Try again";
  return "Find more like this";
}

/** The polite status message for a step; empty when there's nothing to say. */
export function similarStatus(view: SimilarView, count: number): string {
  if (view === "loading") return "Looking for similar videos…";
  if (view === "empty") return SIMILAR_EMPTY;
  if (view === "found") {
    return `Found ${count} ${count === 1 ? "video" : "videos"} like this one.`;
  }
  return "";
}
