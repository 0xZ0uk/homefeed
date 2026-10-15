import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useFeedbackToggle } from "#/components/CardActions";
import {
  UNDONE_MESSAGE,
  ratedMessage,
  withRating,
  type ActionStatus,
} from "#/lib/card-actions";
import {
  NOT_DISMISSED,
  dismissedMessage,
  restoredMessage,
  withItemDismissal,
  withSavedDismissal,
} from "#/lib/dismiss";
import { withFeedback } from "#/lib/feedback";
import {
  dismissItem,
  feedQuery,
  todayFeedQuery,
  undismissItem,
  type Feed,
  type FeedItem,
} from "#/server/feeds";
import { ratingQuery, removeRating, saveRating } from "#/server/ratings";

type Dismissal = Pick<FeedItem, "dismissed_at" | "dismiss_reason">;

/** The key every cached feed starts with (today's, and one by date). */
const FEED_KEY = ["feed"] as const;

/**
 * What the cards of a feed do to it, each shown at once, said in the status
 * line and undoable from it. A change first stops a reload of the feed on its
 * way from putting the older copy back over it; one that can't be saved is
 * taken back and says so, and the feed is loaded again, since a failed request
 * doesn't say whether it got there.
 *
 * - Dismissing an item hides it, and restoring it (the Undo) brings it back.
 *   Both move focus to the status line, since the item, and the focused control
 *   in it, is gone or back. They run in order, so a quick Undo can't overtake
 *   its dismissal, and what the server answers only settles the item's
 *   timestamp, never undoing what happened on screen in the meantime.
 * - "More like this" and "less like this" (see `useFeedbackToggle`) and
 *   ratings change the video wherever it is in the feed, as they are about the
 *   video, not the item.
 */
export function useFeedActions(
  feed: Feed,
  announce: (status: ActionStatus) => void,
) {
  const queryClient = useQueryClient();

  /** Rewrites the feed wherever it is cached: as today's, and by its date. */
  function update(change: (old: Feed) => Feed) {
    const apply = (old: Feed | null | undefined) => (old ? change(old) : old);
    queryClient.setQueryData(todayFeedQuery.queryKey, apply);
    queryClient.setQueryData(feedQuery(feed.date).queryKey, apply);
  }
  const cancelReloads = () => queryClient.cancelQueries({ queryKey: FEED_KEY });
  const reload = () => queryClient.invalidateQueries({ queryKey: FEED_KEY });

  function restore(restoration: { item: FeedItem; dismissed: Dismissal }) {
    restoring.mutate(restoration);
  }

  const restoring = useMutation({
    scope: { id: "feed-item-dismissal" },
    mutationFn: ({ item }: { item: FeedItem; dismissed: Dismissal }) =>
      undismissItem({ data: { id: item.id } }),
    onMutate: async ({ item }) => {
      await cancelReloads();
      update((old) => withItemDismissal(old, item.id, NOT_DISMISSED));
      announce({
        ok: true,
        message: restoredMessage(item.title),
        focus: true,
      });
    },
    onSuccess: (saved) => update((old) => withSavedDismissal(old, saved)),
    onError: (_error, restoration) => {
      const { item, dismissed } = restoration;
      update((old) => withItemDismissal(old, item.id, dismissed));
      // The Undo is offered again: the card is hidden, with nothing else to press.
      announce({
        ok: false,
        message: `Couldn't restore “${item.title}”. Try again.`,
        undo: () => restore(restoration),
        focus: true,
      });
      reload();
    },
  });

  const dismissal = useMutation({
    scope: { id: "feed-item-dismissal" },
    mutationFn: ({ item, reason }: { item: FeedItem; reason: string | null }) =>
      dismissItem({ data: { id: item.id, reason } }),
    onMutate: async ({ item, reason }) => {
      await cancelReloads();
      const dismissed = {
        dismissed_at: new Date().toISOString(),
        dismiss_reason: reason,
      };
      update((old) => withItemDismissal(old, item.id, dismissed));
      announce({
        ok: true,
        message: dismissedMessage(item.title),
        focus: true,
        undo: () => restore({ item, dismissed }),
      });
    },
    onSuccess: (saved) => update((old) => withSavedDismissal(old, saved)),
    onError: (_error, { item }) => {
      update((old) =>
        withItemDismissal(old, item.id, {
          dismissed_at: item.dismissed_at,
          dismiss_reason: item.dismiss_reason,
        }),
      );
      announce({
        ok: false,
        message: `Couldn't dismiss “${item.title}”. Try again later.`,
        focus: true,
      });
      reload();
    },
  });

  const toggleFeedback = useFeedbackToggle({
    apply: async (videoId, signal) => {
      await cancelReloads();
      update((old) => {
        const items = withFeedback(old.items, videoId, signal);
        return items === old.items ? old : { ...old, items };
      });
    },
    reload,
    announce,
  });

  const ratingChange = useMutation({
    scope: { id: "video-rating" },
    mutationFn: ({ videoId, score }: RatingChange) =>
      score === null
        ? removeRating({ data: { videoId } }).then(() => null)
        : saveRating({ data: { videoId, score } }),
    onMutate: async ({ videoId, score }) => {
      await cancelReloads();
      update((old) => rated(old, videoId, score));
    },
    // The watch page shows the rating without asking for it again.
    onSuccess: (saved, { videoId }) =>
      queryClient.setQueryData(ratingQuery(videoId).queryKey, saved),
    onError: (_error, { videoId, title, before }) => {
      update((old) => rated(old, videoId, before));
      announce({
        ok: false,
        message: `Couldn't save your rating of “${title}”. Try again.`,
      });
      reload();
    },
  });

  function rate(item: FeedItem, score: number | null, undoing = false) {
    ratingChange.mutate({
      videoId: item.video_id,
      title: item.title,
      score,
      before: item.rating,
    });
    announce(
      undoing || score === null
        ? { ok: true, message: UNDONE_MESSAGE, focus: true }
        : {
            ok: true,
            message: ratedMessage(item.title, score),
            undo: () => rate({ ...item, rating: score }, item.rating, true),
          },
    );
  }

  return {
    dismiss: (item: FeedItem, reason: string | null) =>
      dismissal.mutate({ item, reason }),
    toggleFeedback,
    rate,
  };
}

interface RatingChange {
  videoId: string;
  title: string;
  /** The new rating; null takes it off. */
  score: number | null;
  /** The rating before, to go back to if saving fails. */
  before: number | null;
}

/** `feed` with the rating of a video set (null clears it) wherever it is. */
function rated(feed: Feed, videoId: string, score: number | null): Feed {
  const items = withRating(feed.items, videoId, score);
  return items === feed.items ? feed : { ...feed, items };
}
