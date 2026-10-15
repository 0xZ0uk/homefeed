/** Helpers for dismissing feed items. Pure, so they're easy to test. */

/** What the card menu calls the group of dismiss reasons. */
export const DISMISS_GROUP_LABEL = "Not for me";

/** Reasons offered when dismissing a feed item; the API also accepts none. */
export const DISMISS_REASONS = [
  "Not interested",
  "Already seen it",
  "Not in the mood",
  "Clickbait",
  "Too long",
] as const;

/** What an item has when it isn't dismissed: what undoing a dismissal restores. */
export const NOT_DISMISSED = {
  dismissed_at: null,
  dismiss_reason: null,
} as const;

/** What the status line says once an item was dismissed. */
export function dismissedMessage(title: string): string {
  return `Dismissed “${title}”.`;
}

/** What the status line says once a dismissal was undone. */
export function restoredMessage(title: string): string {
  return `Restored “${title}”.`;
}

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

/**
 * `feed` with the server's answer for an item: the dismissal fields of `saved`
 * (the timestamp the server gave, say), unless the item has meanwhile been
 * dismissed or restored again, in which case what is on screen stands. Returns
 * `feed` itself when it has no such item or nothing changes.
 */
export function withSavedDismissal<
  T extends Dismissable,
  F extends { items: T[] },
>(feed: F, saved: Dismissable): F {
  const item = feed.items.find((candidate) => candidate.id === saved.id);
  if (!item || (item.dismissed_at === null) !== (saved.dismissed_at === null)) {
    return feed;
  }
  return withItemDismissal(feed, saved.id, {
    dismissed_at: saved.dismissed_at,
    dismiss_reason: saved.dismiss_reason,
  });
}
