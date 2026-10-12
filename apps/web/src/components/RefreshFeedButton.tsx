import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  feedHistoryQuery,
  feedQuery,
  rebuildFeed,
  todayFeedQuery,
} from "#/server/feeds";

/**
 * Poll subscriptions and build a new feed for today. The feed normally
 * refreshes once a day on its own; this is for when that isn't enough.
 */
export function RefreshFeedButton({
  label = "Refresh feed",
}: {
  label?: string;
}) {
  const queryClient = useQueryClient();
  const refresh = useMutation({
    mutationFn: () => rebuildFeed(),
    onSuccess: async (feed) => {
      queryClient.setQueryData(todayFeedQuery.queryKey, feed);
      queryClient.setQueryData(feedQuery(feed.date).queryKey, feed);
      await queryClient.invalidateQueries({
        queryKey: feedHistoryQuery.queryKey,
      });
    },
  });

  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={() => refresh.mutate()}
        disabled={refresh.isPending}
        className="rounded bg-black px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
      >
        {refresh.isPending ? "Refreshing…" : label}
      </button>
      <p role="status" className="text-sm">
        {refresh.isError && (
          <span className="text-red-600">
            Couldn't refresh the feed. Try again later.
          </span>
        )}
      </p>
    </div>
  );
}
