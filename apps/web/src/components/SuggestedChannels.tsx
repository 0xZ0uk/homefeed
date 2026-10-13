import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { ChannelAvatar } from "#/components/ChannelAvatar";
import { Button } from "#/components/ui/button";
import {
  channelUrl,
  featuredByText,
  formatSubscribers,
  hiddenMessage,
} from "#/lib/discover";
import { cn } from "#/lib/utils";
import { channelsQuery, subscribe } from "#/server/channels";
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

interface Status {
  message: string;
  /** Undo what the message announces. */
  undo?: () => void;
}

/** Channels featured by channels I like, each with subscribe and hide actions. */
export function SuggestedChannels() {
  const queryClient = useQueryClient();
  const { data: suggestions } = useSuspenseQuery(suggestedChannelsQuery);
  const [status, setStatus] = useState<Status | null>(null);

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

  const undoHide = useMutation({
    mutationFn: (channelId: string) => unhide({ data: { channelId } }),
    onSuccess: async () => {
      setStatus({ message: "Restored." });
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: suggestedChannelsQuery.queryKey,
        }),
        queryClient.invalidateQueries({ queryKey: channelHidesQuery.queryKey }),
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
            of videos you rated A-- or higher.
          </p>
        </div>
        <Button
          variant="secondary"
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
      <p role="status" className="flex min-h-6 items-center gap-2">
        {status?.message}
        {status?.undo && (
          <button
            type="button"
            onClick={status.undo}
            disabled={undoHide.isPending}
            className="underline"
          >
            Undo
          </button>
        )}
      </p>
      {suggestions.length === 0 ? (
        <p className="text-muted-foreground">
          No suggestions yet. Set a channel's prior to Love or Like in{" "}
          <Link to="/curation" className="underline">
            Curation
          </Link>
          , or rate videos A-- or higher, and channels they feature show up
          here.
        </p>
      ) : (
        <ul className="flex flex-col divide-y" aria-label="Suggested channels">
          {suggestions.map((channel) => (
            <SuggestionRow
              key={channel.channel_id}
              channel={channel}
              onStatus={setStatus}
              onUndo={(channelId) => undoHide.mutate(channelId)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function SuggestionRow({
  channel,
  onStatus,
  onUndo,
}: {
  channel: SuggestedChannel;
  onStatus: (status: Status) => void;
  onUndo: (channelId: string) => void;
}) {
  const queryClient = useQueryClient();
  // Drop the row in place rather than refetching, which would undo a refresh's rotation.
  const invalidateAll = () => {
    queryClient.setQueryData(suggestedChannelsQuery.queryKey, (shown) =>
      shown?.filter((c) => c.channel_id !== channel.channel_id),
    );
    return Promise.all([
      queryClient.invalidateQueries({ queryKey: channelsQuery.queryKey }),
      queryClient.invalidateQueries({ queryKey: channelHidesQuery.queryKey }),
    ]);
  };
  const mutation = useMutation({
    mutationFn: () =>
      subscribe({ data: { url: channelUrl(channel.channel_id) } }),
    onSuccess: async (result) => {
      if (!result.ok) return;
      onStatus({ message: `Subscribed to ${result.channel.title}.` });
      await invalidateAll();
    },
  });
  const hiding = useMutation({
    mutationFn: (kind: HideKind) =>
      hide({ data: { channelId: channel.channel_id, kind } }),
    onSuccess: async (hidden) => {
      onStatus({
        message: hiddenMessage(hidden.kind, channel.title),
        undo: () => onUndo(channel.channel_id),
      });
      await invalidateAll();
    },
  });
  const busy = mutation.isPending || hiding.isPending;
  const failed =
    mutation.isError || (mutation.data !== undefined && !mutation.data.ok);
  const subscribers = formatSubscribers(channel.subscriber_count);

  return (
    <li className="flex flex-col gap-2 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex min-w-48 flex-1 items-center gap-3">
          <Link
            to="/channels/$channelId"
            params={{ channelId: channel.channel_id }}
            className="flex min-w-0 items-center gap-3 rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <ChannelAvatar url={channel.thumbnail_url} title={channel.title} />
            <span className="min-w-0">
              <span className="block truncate font-medium hover:underline">
                {channel.title}
              </span>
              <span className="block truncate text-sm text-muted-foreground">
                {[channel.handle, subscribers].filter(Boolean).join(" · ")}
              </span>
            </span>
          </Link>
        </div>
        <p className="min-w-48 flex-1 text-sm text-muted-foreground">
          {featuredByText(channel.featured_by)}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="lg"
            className="px-4"
            disabled={busy}
            aria-label={`Subscribe to ${channel.title}`}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Subscribing…" : "Subscribe"}
          </Button>
          <Button
            variant="ghost"
            size="lg"
            className="px-3"
            disabled={busy}
            aria-label={`Dismiss ${channel.title}`}
            onClick={() => hiding.mutate("dismissed")}
          >
            Dismiss
          </Button>
          <Button
            variant="ghost"
            size="lg"
            className="px-3"
            disabled={busy}
            aria-label={`Don't show ${channel.title}`}
            onClick={() => hiding.mutate("blocked")}
          >
            Don't show
          </Button>
        </div>
      </div>
      {failed && (
        <p role="alert" className="text-sm text-destructive">
          {mutation.data && !mutation.data.ok
            ? mutation.data.message
            : "Couldn't subscribe. Try again later."}
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
