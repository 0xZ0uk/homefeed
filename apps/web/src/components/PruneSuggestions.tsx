import type { SubscribedChannel } from "@homefeed/api-client";
import { Link } from "@tanstack/react-router";
import { useSyncExternalStore } from "react";

import { ChannelAvatar } from "#/components/ChannelAvatar";
import { ConfirmButton } from "#/components/ConfirmButton";
import { Button } from "#/components/ui/button";
import {
  useChannelActions,
  type ChannelStatus,
} from "#/components/use-channel-actions";
import {
  DORMANT_MIN_PICKS,
  PICKS_WINDOW_DAYS,
  PRUNE_DISMISSED_KEY,
  parseDismissed,
  withoutDismissed,
  type ChannelHealth,
} from "#/lib/channel-health";
import { MONTH_MUTE_DAYS } from "#/lib/channels";

/*
 * Which channels the panel was dismissed for, kept in the browser. The panel
 * returns when a channel it hasn't been dismissed for starts to qualify.
 */
const listeners = new Set<() => void>();
// What was dismissed since the page loaded, if the browser wouldn't save it.
let dismissedNow: string | null = null;

function readDismissed(): string {
  if (dismissedNow !== null) return dismissedNow;
  try {
    return window.localStorage.getItem(PRUNE_DISMISSED_KEY) ?? "";
  } catch {
    return "";
  }
}

function subscribeToDismissed(listener: () => void) {
  const onStorage = (event: StorageEvent) => {
    if (event.key !== PRUNE_DISMISSED_KEY) return;
    dismissedNow = null; // another tab saved something: read it
    listener();
  };
  listeners.add(listener);
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

function dismissChannels(current: string[], channelIds: string[]) {
  dismissedNow = JSON.stringify([...new Set([...current, ...channelIds])]);
  try {
    window.localStorage.setItem(PRUNE_DISMISSED_KEY, dismissedNow);
  } catch {
    // Storage may be full or blocked; the panel just comes back next time.
  }
  for (const listener of listeners) listener();
}

/**
 * The subscriptions that keep landing in the feed without being watched, with a
 * way to mute each for a month or unsubscribe. Dismissing the panel hides it
 * for the channels it lists.
 */
export function PruneSuggestions({
  channels,
  health,
  onStatus,
}: {
  /** The channels that qualify (see `dormantChannels`). */
  channels: SubscribedChannel[];
  health: ReadonlyMap<string, ChannelHealth>;
  onStatus: (status: ChannelStatus) => void;
}) {
  // The server renders it as if nothing was dismissed; the browser may know better.
  const raw = useSyncExternalStore(
    subscribeToDismissed,
    readDismissed,
    () => "",
  );
  const dismissed = parseDismissed(raw);
  const shown = withoutDismissed(channels, dismissed);
  if (shown.length === 0) return null;

  return (
    <section
      aria-labelledby="prune-heading"
      className="flex flex-col gap-3 rounded-xl border bg-card p-4 text-card-foreground"
    >
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-64 flex-1 flex-col gap-1">
          <h2 id="prune-heading" className="text-lg font-semibold">
            These channels keep showing up but you don't watch them
          </h2>
          <p className="text-sm text-muted-foreground">
            Each had {DORMANT_MIN_PICKS} or more picks in the last{" "}
            {PICKS_WINDOW_DAYS} days, and you watched none of them.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="lg"
          className="px-4"
          onClick={() =>
            dismissChannels(
              dismissed,
              shown.map((channel) => channel.channel_id),
            )
          }
        >
          Not now
        </Button>
      </div>
      <ul
        aria-label="Channels you don't watch"
        className="flex flex-col divide-y"
      >
        {shown.map((channel) => (
          <PruneRow
            key={channel.channel_id}
            channel={channel}
            picks={health.get(channel.channel_id)?.picks ?? 0}
            onStatus={onStatus}
          />
        ))}
      </ul>
    </section>
  );
}

function PruneRow({
  channel,
  picks,
  onStatus,
}: {
  channel: SubscribedChannel;
  picks: number;
  onStatus: (status: ChannelStatus) => void;
}) {
  // Both ways out take the row out of the panel, so the message gets the focus.
  const actions = useChannelActions(channel, (status) =>
    onStatus({ ...status, moveFocus: true }),
  );
  const { title } = channel;

  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3 first:pt-0 last:pb-0">
      <div className="flex min-w-48 flex-1 items-center gap-3">
        <ChannelAvatar url={channel.thumbnail_url} title={title} />
        <div className="min-w-0">
          <Link
            to="/channels/$channelId"
            params={{ channelId: channel.channel_id }}
            className="block rounded-sm font-medium break-words outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {title}
          </Link>
          <p className="text-sm text-muted-foreground">
            {picks} picks, none watched
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="lg"
          className="px-4"
          disabled={actions.busy}
          aria-label={`Mute for a month: ${title}`}
          onClick={() => actions.update.mutate({ mute_days: MONTH_MUTE_DAYS })}
        >
          Mute for a month
        </Button>
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
      </div>
      {actions.failed && (
        <p role="alert" className="w-full text-sm text-destructive">
          Couldn't save that change. Try again.
        </p>
      )}
    </li>
  );
}
