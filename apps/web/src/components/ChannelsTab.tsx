import type { SubscribedChannel } from "@homefeed/api-client";
import {
  useMutation,
  useQuery,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Pin } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { ChannelAvatar } from "#/components/ChannelAvatar";
import { ChannelMuteMenu } from "#/components/ChannelMuteMenu";
import { ConfirmButton } from "#/components/ConfirmButton";
import { PruneSuggestions } from "#/components/PruneSuggestions";
import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import {
  formatMuteEnd,
  useChannelActions,
  type ChannelStatus,
} from "#/components/use-channel-actions";
import {
  CHANNEL_SORTS,
  PICKS_WINDOW_DAYS,
  describeHealth,
  dormantChannels,
  isChannelSort,
  sortChannels,
  type ChannelHealth,
  type ChannelSort,
} from "#/lib/channel-health";
import {
  MONTH_MUTE_DAYS,
  PRIORS,
  PRIOR_LABELS,
  muteState,
  trialLabel,
  type Prior,
} from "#/lib/channels";
import { cn } from "#/lib/utils";
import {
  channelHealthQuery,
  channelsQuery,
  subscribe,
  updatePrefs,
} from "#/server/channels";

const FIELD =
  "rounded-lg border border-input bg-transparent outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";

/**
 * Subscribe by URL, and look after the subscribed channels: set each one's
 * preference, pin and mute, see how much of it you watch, sort by that, and
 * keep or end the ones on trial. A panel at the top suggests letting go of
 * channels that keep showing up without being watched.
 */
export function ChannelsTab() {
  const { data: channels } = useSuspenseQuery(channelsQuery);
  const { data: healthList } = useQuery(channelHealthQuery);
  const health = useMemo(
    () =>
      healthList &&
      new Map(healthList.map((stats) => [stats.channel_id, stats])),
    [healthList],
  );
  // One "now" per render pass keeps every row's ages and countdowns consistent.
  const [now] = useState(() => new Date());
  const [sort, setSort] = useState<ChannelSort>("title");
  const [status, setStatus] = useState<ChannelStatus | null>(null);
  const statusRef = useRef<HTMLParagraphElement>(null);

  // When the channel acted on is gone, keyboard focus has nowhere else to be.
  useEffect(() => {
    if (status?.moveFocus) statusRef.current?.focus();
  }, [status]);

  const queryClient = useQueryClient();
  const unmute = useMutation({
    mutationFn: ({ channelId }: { channelId: string; title: string }) =>
      updatePrefs({ data: { channelId, muted: false } }),
    onSuccess: (_channel, { title }) =>
      setStatus({ message: `Unmuted ${title}.`, moveFocus: true }),
    onError: () => setStatus({ message: "Couldn't unmute. Try again." }),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: channelsQuery.queryKey }),
  });

  const sorted = useMemo(
    () => sortChannels(channels, health, sort),
    [channels, health, sort],
  );
  const dormant = useMemo(
    () => dormantChannels(channels, health, now),
    [channels, health, now],
  );

  return (
    <div className="flex flex-col gap-6">
      <SubscribeForm />
      {channels.length === 0 ? (
        <p className="text-muted-foreground">
          No subscriptions yet. Paste a channel link above to add one, or find
          new ones on{" "}
          <Link to="/discover" className="underline">
            Discover
          </Link>
          .
        </p>
      ) : (
        <>
          {health && (
            <PruneSuggestions
              channels={dormant}
              health={health}
              onStatus={setStatus}
            />
          )}
          <section
            aria-labelledby="channels-heading"
            className="flex flex-col gap-2"
          >
            <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
              <div className="flex min-w-64 flex-1 flex-col gap-1">
                <h2 id="channels-heading" className="text-xl font-semibold">
                  Your channels
                </h2>
                <p className="text-sm text-muted-foreground">
                  {channels.length}{" "}
                  {channels.length === 1 ? "channel" : "channels"}. Picks are
                  the videos Homefeed put in your feed in the last{" "}
                  {PICKS_WINDOW_DAYS} days.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <label htmlFor="channel-sort" className="text-sm">
                  Sort by
                </label>
                <select
                  id="channel-sort"
                  value={sort}
                  onChange={(event) => {
                    if (isChannelSort(event.target.value)) {
                      setSort(event.target.value);
                    }
                  }}
                  className={cn(FIELD, "px-2 py-1 text-sm")}
                >
                  {CHANNEL_SORTS.map(({ value, label }) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <p
              ref={statusRef}
              role="status"
              tabIndex={-1}
              className="flex min-h-6 flex-wrap items-center gap-x-3 gap-y-1 text-sm focus:outline-none"
            >
              {status?.message}
              {status?.unmute && (
                <button
                  type="button"
                  disabled={unmute.isPending}
                  onClick={() => status.unmute && unmute.mutate(status.unmute)}
                  className="rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  Undo
                </button>
              )}
            </p>
            <ul className="flex flex-col divide-y" aria-label="Subscriptions">
              {sorted.map((channel) => (
                <ChannelRow
                  key={channel.channel_id}
                  channel={channel}
                  stats={health?.get(channel.channel_id)}
                  now={now}
                  onStatus={setStatus}
                />
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}

function SubscribeForm() {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const mutation = useMutation({
    mutationFn: (url: string) => subscribe({ data: { url } }),
    onSuccess: async (result) => {
      if (result.ok) {
        setUrl("");
        await queryClient.invalidateQueries({
          queryKey: channelsQuery.queryKey,
        });
      }
    },
  });
  const result = mutation.data;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (url.trim()) mutation.mutate(url);
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <label htmlFor="channel-url" className="font-medium">
        Subscribe to a channel
      </label>
      <div className="flex gap-2">
        <input
          id="channel-url"
          type="text"
          inputMode="url"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="https://www.youtube.com/@channel"
          required
          aria-invalid={result?.ok === false}
          aria-describedby="subscribe-status"
          className={cn(FIELD, "min-w-0 flex-1 px-3 py-2")}
        />
        <Button
          type="submit"
          size="lg"
          className="px-4"
          disabled={mutation.isPending}
        >
          {mutation.isPending ? "Subscribing…" : "Subscribe"}
        </Button>
      </div>
      <p id="subscribe-status" role="status" className="min-h-6">
        {mutation.isError && (
          <span className="text-destructive">
            Couldn't subscribe. Try again later.
          </span>
        )}
        {result?.ok === false && (
          <span className="text-destructive">{result.message}</span>
        )}
        {result?.ok === true &&
          (result.created
            ? `Subscribed to ${result.channel.title}.`
            : `You're already subscribed to ${result.channel.title}.`)}
      </p>
    </form>
  );
}

function ChannelRow({
  channel,
  stats,
  now,
  onStatus,
}: {
  channel: SubscribedChannel;
  stats: ChannelHealth | undefined;
  now: Date;
  onStatus: (status: ChannelStatus) => void;
}) {
  const actions = useChannelActions(channel, onStatus);
  const { title } = channel;
  const priorId = `prior-${channel.channel_id}`;
  const mute = muteState(channel, now);
  const trial = trialLabel(channel.trial_until, now);
  const summary = describeHealth(stats, now);

  return (
    <li className="flex flex-wrap items-start gap-x-6 gap-y-3 py-4">
      <div className="flex min-w-60 flex-1 items-start gap-3">
        <ChannelAvatar url={channel.thumbnail_url} title={title} />
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <p className="flex flex-wrap items-baseline gap-x-2">
            <Link
              to="/channels/$channelId"
              params={{ channelId: channel.channel_id }}
              className="rounded-sm font-medium break-words outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {title}
            </Link>
            {channel.handle && (
              <span className="text-sm text-muted-foreground">
                {channel.handle}
              </span>
            )}
          </p>
          {summary && (
            <p
              className="text-sm text-muted-foreground"
              suppressHydrationWarning
            >
              {summary}
            </p>
          )}
          {mute.kind === "until" && (
            <p className="text-sm" suppressHydrationWarning>
              Muted until{" "}
              <time dateTime={mute.until}>{formatMuteEnd(mute.until)}</time>
            </p>
          )}
          {trial && (
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <Badge variant="outline" className="h-6 px-2.5">
                <span suppressHydrationWarning>{trial}</span>
              </Badge>
              <Button
                type="button"
                variant="outline"
                size="lg"
                className="px-4"
                disabled={actions.busy}
                aria-label={`Keep ${title}`}
                onClick={() => actions.keep.mutate()}
              >
                {actions.keep.isPending ? "Keeping…" : "Keep"}
              </Button>
              <ConfirmButton
                disabled={actions.busy}
                aria-label={`End trial of ${title}`}
                title={`End the trial of ${title}?`}
                description="You'll be unsubscribed, and it won't be suggested on Discover again right away. You can restore it in Settings."
                confirmLabel="End trial"
                className="px-4"
                onConfirm={() => actions.end.mutate()}
              >
                End trial
              </ConfirmButton>
            </div>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2">
          <label htmlFor={priorId} className="text-sm">
            Preference
          </label>
          <select
            id={priorId}
            value={channel.prior}
            disabled={actions.busy}
            aria-label={`Preference for ${title}`}
            onChange={(event) =>
              actions.update.mutate({ prior: event.target.value as Prior })
            }
            className={cn(FIELD, "px-2 py-1.5 text-sm")}
          >
            {PRIORS.map((prior) => (
              <option key={prior} value={prior}>
                {PRIOR_LABELS[prior]}
              </option>
            ))}
          </select>
        </div>
        <Button
          type="button"
          variant="outline"
          size="lg"
          className="px-3 aria-pressed:border-foreground/40 aria-pressed:bg-secondary"
          disabled={actions.busy}
          aria-pressed={channel.pinned}
          aria-label={`Pinned: ${title}`}
          onClick={() => actions.update.mutate({ pinned: !channel.pinned })}
        >
          <Pin className={cn(channel.pinned && "fill-current")} />
          Pinned
        </Button>
        <ChannelMuteMenu
          title={title}
          state={mute}
          disabled={actions.busy}
          onMute={() => actions.update.mutate({ muted: true })}
          onMuteForAMonth={() =>
            actions.update.mutate({ mute_days: MONTH_MUTE_DAYS })
          }
          onUnmute={() => actions.update.mutate({ muted: false })}
        />
        {!trial && (
          <ConfirmButton
            disabled={actions.busy}
            aria-label={`Unsubscribe from ${title}`}
            title={`Unsubscribe from ${title}?`}
            description="It stops showing up in your feed, and its preference and pin are forgotten. You can subscribe again any time."
            confirmLabel="Unsubscribe"
            className="px-4"
            onConfirm={() => actions.remove.mutate()}
          >
            Unsubscribe
          </ConfirmButton>
        )}
      </div>
      {actions.failed && (
        <p role="alert" className="w-full text-sm text-destructive">
          Couldn't save that change. Try again.
        </p>
      )}
    </li>
  );
}
