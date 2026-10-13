import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { ChannelAvatar } from "#/components/ChannelAvatar";
import { Button } from "#/components/ui/button";
import { hideKindLabel } from "#/lib/discover";
import {
  channelHidesQuery,
  hide,
  unhide,
  type ChannelHide,
} from "#/server/channel-hides";
import { suggestedChannelsQuery } from "#/server/discover";

/** Channels hidden from Discover or the feed, with a way to bring them back. */
export function HiddenChannels() {
  const { data: hides } = useSuspenseQuery(channelHidesQuery);

  return (
    <section
      aria-labelledby="hidden-channels-heading"
      className="flex flex-col gap-3"
    >
      <div className="flex flex-col gap-1">
        <h3 id="hidden-channels-heading" className="text-lg font-semibold">
          Hidden channels
        </h3>
        <p className="text-muted-foreground">
          Channels you dismissed from Discover or kept out of your feed.
        </p>
      </div>
      {hides.length === 0 ? (
        <p className="text-muted-foreground">
          No hidden channels. Use Dismiss or Don't show on Discover to hide one.
        </p>
      ) : (
        <ul className="flex flex-col divide-y" aria-label="Hidden channels">
          {hides.map((item) => (
            <HiddenRow key={item.channel_id} item={item} />
          ))}
        </ul>
      )}
    </section>
  );
}

function HiddenRow({ item }: { item: ChannelHide }) {
  const queryClient = useQueryClient();
  const settle = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: channelHidesQuery.queryKey }),
      queryClient.invalidateQueries({
        queryKey: suggestedChannelsQuery.queryKey,
      }),
    ]);
  const restore = useMutation({
    mutationFn: () => unhide({ data: { channelId: item.channel_id } }),
    onSuccess: settle,
  });
  const demote = useMutation({
    mutationFn: () =>
      hide({ data: { channelId: item.channel_id, kind: "dismissed" } }),
    onSuccess: settle,
  });
  const busy = restore.isPending || demote.isPending;
  const date = new Date(item.hidden_at);
  const failed = restore.isError || demote.isError;

  return (
    <li className="flex flex-col gap-2 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex min-w-48 flex-1 items-center gap-3">
          <ChannelAvatar url={item.thumbnail_url} title={item.title} />
          <div className="min-w-0">
            <Link
              to="/channels/$channelId"
              params={{ channelId: item.channel_id }}
              className="block truncate font-medium hover:underline"
            >
              {item.title}
            </Link>
            <p className="text-sm text-muted-foreground">
              {hideKindLabel(item.kind)}
              {!Number.isNaN(date.getTime()) && (
                <>
                  {" · "}
                  <time dateTime={item.hidden_at} suppressHydrationWarning>
                    {date.toLocaleDateString("en", {
                      year: "numeric",
                      month: "short",
                      day: "numeric",
                    })}
                  </time>
                </>
              )}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            size="lg"
            className="px-4"
            disabled={busy}
            aria-label={`Restore ${item.title}`}
            onClick={() => restore.mutate()}
          >
            {restore.isPending ? "Restoring…" : "Restore"}
          </Button>
          {item.kind === "blocked" && (
            <Button
              variant="ghost"
              size="lg"
              className="px-3"
              disabled={busy}
              aria-label={`Dismiss only ${item.title}`}
              onClick={() => demote.mutate()}
            >
              Dismiss only
            </Button>
          )}
        </div>
      </div>
      {failed && (
        <p role="alert" className="text-sm text-destructive">
          Couldn't update this channel. Try again later.
        </p>
      )}
    </li>
  );
}
