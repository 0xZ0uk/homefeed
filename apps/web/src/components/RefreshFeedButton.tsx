import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { Button } from "#/components/ui/button";
import { cn } from "#/lib/utils";
import { discoveryVideosQuery } from "#/server/discover";
import {
  feedQuery,
  rebuildFeed,
  todayFeedQuery,
} from "#/server/feeds";

/**
 * Poll subscriptions and build a new feed for today. The feed normally
 * refreshes once a day on its own; this is for when that isn't enough.
 *
 * `compact` fits it in the masthead: masthead-sized, icon-only on narrow
 * screens, with a shorter error.
 */
export function RefreshFeedButton({
  label = "Refresh feed",
  variant = "default",
  compact = false,
}: {
  label?: string;
  variant?: "default" | "secondary";
  compact?: boolean;
}) {
  const queryClient = useQueryClient();
  const refresh = useMutation({
    mutationFn: () => rebuildFeed(),
    onSuccess: (feed) => {
      queryClient.setQueryData(todayFeedQuery.queryKey, feed);
      queryClient.setQueryData(feedQuery(feed.date).queryKey, feed);
      void queryClient.invalidateQueries({
        queryKey: discoveryVideosQuery.queryKey,
      });
    },
  });

  return (
    <div className={cn("flex items-center", compact ? "gap-2" : "gap-3")}>
      <p
        role="status"
        className={cn("text-sm empty:hidden", compact && "order-first")}
      >
        {refresh.isError && (
          <span className="text-destructive">
            {compact
              ? "Couldn't refresh."
              : "Couldn't refresh the feed. Try again later."}
          </span>
        )}
      </p>
      <Button
        variant={variant}
        size="lg"
        onClick={() => refresh.mutate()}
        disabled={refresh.isPending}
        className={compact ? "gap-2 px-3 sm:pr-4" : "px-4"}
      >
        <RefreshCw
          className={cn(refresh.isPending && "motion-safe:animate-spin")}
        />
        <span className={cn(compact && "max-sm:sr-only")}>
          {refresh.isPending ? "Refreshing…" : label}
        </span>
      </Button>
    </div>
  );
}
