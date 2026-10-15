import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ChannelAvatar } from "#/components/ChannelAvatar";
import { ChannelPreview } from "#/components/ChannelPreview";
import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import {
  channelUrl,
  featuredByText,
  formatSubscribers,
  hiddenMessage,
} from "#/lib/discover";
import { TOP_TIER_THRESHOLD } from "#/lib/scores";
import { cn } from "#/lib/utils";
import {
  channelsQuery,
  startTrial,
  subscribe,
  unsubscribe,
} from "#/server/channels";
import {
  channelHidesQuery,
  hide,
  unhide,
  type HideKind,
} from "#/server/channel-hides";
import {
  refreshSuggestions,
  suggestedChannelsQuery,
  type SuggestedChannel,
} from "#/server/discover";

/** What Undo does: show a hidden channel again, or unsubscribe from a new one. */
interface Undo {
  kind: "unhide" | "unsubscribe";
  channelId: string;
  title: string;
}

interface Status {
  message: string;
  undo?: Undo;
  /** Offer a way to the subscriptions, where a new trial is kept or ended. */
  seeSubscriptions?: boolean;
  /** The card that was acted on is gone, so keyboard focus goes to the message. */
  moveFocus?: boolean;
}

/**
 * Channels featured by channels I like, as cards to size up and decide on:
 * who the channel is and why it's suggested, a preview of its latest uploads,
 * and what to do with it: subscribe, try it for two weeks, or leave it.
 */
export function SuggestedChannels() {
  const queryClient = useQueryClient();
  const { data: suggestions } = useSuspenseQuery(suggestedChannelsQuery);
  const [status, setStatus] = useState<Status | null>(null);
  const statusRef = useRef<HTMLParagraphElement>(null);

  // Whoever acted on a card has nothing left to focus once it's gone.
  useEffect(() => {
    if (status?.moveFocus) statusRef.current?.focus();
  }, [status]);

  const refresh = useMutation({
    mutationFn: () =>
      refreshSuggestions({
        data: { exclude: suggestions.map((c) => c.channel_id) },
      }),
    onSuccess: (channels) => {
      const shown = new Set(suggestions.map((c) => c.channel_id));
      const fresh = channels.filter((c) => !shown.has(c.channel_id)).length;
      queryClient.setQueryData(suggestedChannelsQuery.queryKey, channels);
      setStatus({
        message:
          fresh === 0
            ? "No new channels found. Try again later."
            : `Found ${fresh} new ${fresh === 1 ? "channel" : "channels"}.`,
      });
    },
    onError: () =>
      setStatus({ message: "Couldn't refresh suggestions. Try again later." }),
  });

  const undo = useMutation({
    mutationFn: ({ kind, channelId }: Undo) =>
      kind === "unhide"
        ? unhide({ data: { channelId } })
        : unsubscribe({ data: { channelId } }),
    onSuccess: async (_result, { kind, title }) => {
      setStatus({
        message:
          kind === "unhide"
            ? `Restored ${title}.`
            : `Unsubscribed from ${title}.`,
        moveFocus: true,
      });
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: suggestedChannelsQuery.queryKey,
        }),
        queryClient.invalidateQueries({ queryKey: channelHidesQuery.queryKey }),
        queryClient.invalidateQueries({ queryKey: channelsQuery.queryKey }),
      ]);
    },
    onError: () => setStatus({ message: "Couldn't undo. Try again later." }),
  });

  return (
    <section
      aria-labelledby="suggested-heading"
      className="flex flex-col gap-3"
    >
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-64 flex-1 flex-col gap-1">
          <h2 id="suggested-heading" className="text-xl font-semibold">
            Suggested channels
          </h2>
          <p className="text-muted-foreground">
            Channels featured by the channels you love or like, and by channels
            of videos you rated {TOP_TIER_THRESHOLD} or higher.
          </p>
          <p className="text-sm text-muted-foreground">
            <strong className="font-medium text-foreground">Not now</strong>{" "}
            skips a channel here.{" "}
            <strong className="font-medium text-foreground">
              Hide channel
            </strong>{" "}
            also keeps its videos out of your feed.
          </p>
        </div>
        <Button
          variant="outline"
          size="lg"
          className="px-4"
          disabled={refresh.isPending}
          onClick={() => refresh.mutate()}
        >
          <RefreshCw
            className={cn(refresh.isPending && "motion-safe:animate-spin")}
          />
          {refresh.isPending ? "Refreshing…" : "Refresh"}
        </Button>
      </div>
      <p
        ref={statusRef}
        role="status"
        tabIndex={-1}
        className="flex min-h-6 flex-wrap items-center gap-x-3 gap-y-1 focus:outline-none"
      >
        {status?.message}
        {status?.undo && (
          <button
            type="button"
            onClick={() => status.undo && undo.mutate(status.undo)}
            disabled={undo.isPending}
            className="rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            Undo
          </button>
        )}
        {status?.seeSubscriptions && (
          <Link
            to="/subscriptions"
            className="rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            Open Subscriptions
          </Link>
        )}
      </p>
      {suggestions.length === 0 ? (
        <p className="text-muted-foreground">
          No suggestions yet. Set a channel's preference to Love or Like in{" "}
          <Link to="/subscriptions" className="underline">
            Subscriptions
          </Link>
          , or rate videos {TOP_TIER_THRESHOLD} or higher, and channels they
          feature show up here.
        </p>
      ) : (
        <ul className="flex flex-col gap-4" aria-label="Suggested channels">
          {suggestions.map((channel) => (
            <SuggestionCard
              key={channel.channel_id}
              channel={channel}
              onStatus={setStatus}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function SuggestionCard({
  channel,
  onStatus,
}: {
  channel: SuggestedChannel;
  onStatus: (status: Status) => void;
}) {
  const queryClient = useQueryClient();
  const { channel_id: channelId, title } = channel;
  // Drop the card in place rather than refetching, which would undo a refresh's rotation.
  const settle = () => {
    queryClient.setQueryData(suggestedChannelsQuery.queryKey, (shown) =>
      shown?.filter((c) => c.channel_id !== channelId),
    );
    return Promise.all([
      queryClient.invalidateQueries({ queryKey: channelsQuery.queryKey }),
      queryClient.invalidateQueries({ queryKey: channelHidesQuery.queryKey }),
    ]);
  };
  const subscribing = useMutation({
    mutationFn: () => subscribe({ data: { url: channelUrl(channelId) } }),
    onSuccess: async (result) => {
      if (!result.ok) return;
      onStatus({
        message: `Subscribed to ${result.channel.title}.`,
        undo: { kind: "unsubscribe", channelId, title: result.channel.title },
        moveFocus: true,
      });
      await settle();
    },
  });
  const trying = useMutation({
    mutationFn: () => startTrial({ data: { channelId } }),
    onSuccess: async ({ created }) => {
      onStatus(
        created
          ? {
              message: `Started a 2-week trial of ${title}. You decide in Subscriptions whether to keep it.`,
              undo: { kind: "unsubscribe", channelId, title },
              seeSubscriptions: true,
              moveFocus: true,
            }
          : {
              message: `You're already subscribed to ${title}.`,
              moveFocus: true,
            },
      );
      await settle();
    },
  });
  const hiding = useMutation({
    mutationFn: (kind: HideKind) => hide({ data: { channelId, kind } }),
    onSuccess: async (hidden) => {
      onStatus({
        message: hiddenMessage(hidden.kind, title),
        undo: { kind: "unhide", channelId, title },
        moveFocus: true,
      });
      await settle();
    },
  });
  const busy = subscribing.isPending || trying.isPending || hiding.isPending;
  const subscribeFailed =
    subscribing.isError ||
    (subscribing.data !== undefined && !subscribing.data.ok);
  const meta = [channel.handle, formatSubscribers(channel.subscriber_count)]
    .filter(Boolean)
    .join(" · ");
  const tags = channel.top_tags ?? [];

  return (
    <li className="flex flex-col gap-3 rounded-xl border bg-card p-4 text-card-foreground">
      <div className="flex items-start gap-4">
        <ChannelAvatar
          url={channel.thumbnail_url}
          title={title}
          className="size-14"
        />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h3 className="text-lg leading-snug font-semibold break-words">
            <Link
              to="/channels/$channelId"
              params={{ channelId }}
              className="rounded-sm outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {title}
            </Link>
          </h3>
          {meta && <p className="text-sm text-muted-foreground">{meta}</p>}
          <p className="text-sm">{featuredByText(channel.featured_by)}</p>
          {tags.length > 0 && (
            <ul
              aria-label={`Topics of ${title}`}
              className="mt-1 flex flex-wrap gap-1.5"
            >
              {tags.map((tag) => (
                <li key={tag}>
                  <Badge variant="secondary">{tag}</Badge>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <ChannelPreview channelId={channelId} title={title} />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="lg"
          className="px-4"
          disabled={busy}
          aria-label={`Subscribe to ${title}`}
          onClick={() => subscribing.mutate()}
        >
          {subscribing.isPending ? "Subscribing…" : "Subscribe"}
        </Button>
        <Button
          variant="outline"
          size="lg"
          className="px-4"
          disabled={busy}
          aria-label={`Try for 2 weeks: ${title}`}
          onClick={() => trying.mutate()}
        >
          {trying.isPending ? "Starting…" : "Try for 2 weeks"}
        </Button>
        <span className="flex flex-wrap items-center gap-2 sm:ml-auto">
          <Button
            variant="outline"
            size="lg"
            className="px-4"
            disabled={busy}
            aria-label={`Not now for ${title}`}
            onClick={() => hiding.mutate("dismissed")}
          >
            Not now
          </Button>
          <Button
            variant="outline"
            size="lg"
            className="px-4"
            disabled={busy}
            aria-label={`Hide channel: ${title}`}
            onClick={() => hiding.mutate("blocked")}
          >
            Hide channel
          </Button>
        </span>
      </div>
      {subscribeFailed && (
        <p role="alert" className="text-sm text-destructive">
          {subscribing.data && !subscribing.data.ok
            ? subscribing.data.message
            : "Couldn't subscribe. Try again later."}
        </p>
      )}
      {trying.isError && (
        <p role="alert" className="text-sm text-destructive">
          Couldn't start the trial. Try again later.
        </p>
      )}
      {hiding.isError && (
        <p role="alert" className="text-sm text-destructive">
          Couldn't hide this channel. Try again later.
        </p>
      )}
    </li>
  );
}
