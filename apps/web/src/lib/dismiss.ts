/** Helpers for dismissing feed items. Pure, so they're easy to test. */

/** Reasons offered when dismissing a feed item; the API also accepts none. */
export const DISMISS_REASONS = [
  "Not interested",
  "Already seen it",
  "Not in the mood",
  "Clickbait",
  "Too long",
] as const;

type Dismissable = {
  id: number;
  dismissed_at: string | null;
  dismiss_reason: string | null;
};

/** Items that haven't been dismissed, in their original order. */
export function undismissedItems<T extends Dismissable>(items: T[]): T[] {
  return items.filter((item) => item.dismissed_at === null);
}

/**
 * `feed` with the dismissal fields of item `itemId` set from `dismissal`: a
 * local guess, the previous values (to undo the guess) or the server's copy of
 * the whole item. Returns `feed` itself when it has no such item.
 */
export function withItemDismissal<
  T extends Dismissable,
  F extends { items: T[] },
>(
  feed: F,
  itemId: number,
  dismissal: Pick<T, "dismissed_at" | "dismiss_reason"> | T,
): F {
  if (!feed.items.some((item) => item.id === itemId)) return feed;
  return {
    ...feed,
    items: feed.items.map((item) =>
      item.id === itemId ? { ...item, ...dismissal, id: itemId } : item,
    ),
  };
}
