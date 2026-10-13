import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { Button } from "#/components/ui/button";
import { cn } from "#/lib/utils";
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
  variant = "default",
}: {
  label?: string;
  variant?: "default" | "secondary";
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
      <Button
        variant={variant}
        size="lg"
        onClick={() => refresh.mutate()}
        disabled={refresh.isPending}
        className="px-4"
      >
        <RefreshCw
          className={cn(refresh.isPending && "motion-safe:animate-spin")}
        />
        {refresh.isPending ? "Refreshing…" : label}
      </Button>
      <p role="status" className="text-sm empty:hidden">
        {refresh.isError && (
          <span className="text-destructive">
            Couldn't refresh the feed. Try again later.
          </span>
        )}
      </p>
    </div>
  );
}
