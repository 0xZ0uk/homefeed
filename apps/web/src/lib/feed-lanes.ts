/**
 * Today's feed in two lanes: what's new to me, from channels I don't follow,
 * and what comes from the channels I do. Pure, so the split and what an empty
 * lane says are easy to test.
 */

export type LaneId = "fresh" | "own";

/** The lanes in the order the page shows them, with their headings. */
export const LANES: readonly { id: LaneId; title: string }[] = [
  { id: "fresh", title: "New to you" },
  { id: "own", title: "From your channels" },
];

export type Lanes<T> = Record<LaneId, T[]>;

/**
 * `items` split by where they come from, each lane in the order given. An
 * item whose channel isn't known to be one I subscribe to counts as new only
 * when the feed says so (`channel_subscribed` is false).
 */
export function splitLanes<T extends { channel_subscribed?: boolean }>(
  items: readonly T[],
): Lanes<T> {
  const lanes: Lanes<T> = { fresh: [], own: [] };
  for (const item of items) {
    lanes[item.channel_subscribed === false ? "fresh" : "own"].push(item);
  }
  return lanes;
}

/** Why a lane has nothing to show. */
export type EmptyReason = "none" | "dismissed" | "filtered";

/**
 * Why a lane shows nothing, or null when it shows something. `total` is how
 * many videos the feed has in the lane, `kept` how many are left once the
 * dismissed ones are out and `visible` how many once the filter is applied.
 */
export function emptyReason(
  total: number,
  kept: number,
  visible: number,
): EmptyReason | null {
  if (visible > 0) return null;
  if (kept > 0) return "filtered";
  return total > 0 ? "dismissed" : "none";
}

/** What an empty lane says, and what to do about it. `filterLabel` is the
 * chip that is on, which "filtered" blames. */
export function laneEmptyMessage(
  lane: LaneId,
  reason: EmptyReason,
  filterLabel: string,
): string {
  switch (reason) {
    case "filtered":
      return `Nothing here matches “${filterLabel}”. Choose All to see the rest.`;
    case "dismissed":
      return lane === "fresh"
        ? "You've dismissed everything new to you. Dismissed videos won't come back."
        : "You've dismissed everything from your channels. Dismissed videos won't come back.";
    case "none":
      return lane === "fresh"
        ? "Today's feed has no picks from channels you don't follow. They turn up as you rate videos and follow tags."
        : "Nothing from your channels today. Subscribe to more channels on the Subscriptions page, then rebuild the feed.";
  }
}
