import type { SubscribedChannel } from "@homefeed/api-client";
import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import {
  PRIORS,
  channelsQuery,
  subscribe,
  unsubscribe,
  updatePrefs,
  type ChannelPrefsUpdate,
  type Prior,
} from "#/server/channels";
import { showsImages } from "#/lib/display";
import { displayPrefsQuery } from "#/server/display";

const PRIOR_LABELS: Record<Prior, string> = {
  love: "Love",
  like: "Like",
  neutral: "Neutral",
  skeptical: "Skeptical",
};

/** Subscribe by URL, and set each subscribed channel's prior, pin and mute. */
export function ChannelsTab() {
  const { data: channels } = useSuspenseQuery(channelsQuery);
  const { data: display } = useSuspenseQuery(displayPrefsQuery);
  const avatars = showsImages(display);

  return (
    <div className="flex flex-col gap-6">
      <SubscribeForm />
      {channels.length === 0 ? (
        <p className="text-muted-foreground">
          No subscriptions yet. Paste a channel link above to add one.
        </p>
      ) : (
        <ul className="flex flex-col divide-y" aria-label="Subscriptions">
          {channels.map((channel) => (
            <ChannelRow
              key={channel.channel_id}
              channel={channel}
              avatar={avatars}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function useInvalidateChannels() {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({ queryKey: channelsQuery.queryKey });
}

function SubscribeForm() {
  const invalidate = useInvalidateChannels();
  const [url, setUrl] = useState("");
  const mutation = useMutation({
    mutationFn: (url: string) => subscribe({ data: { url } }),
    onSuccess: async (result) => {
      if (result.ok) {
        setUrl("");
        await invalidate();
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
          className="min-w-0 flex-1 rounded-lg border border-input bg-transparent outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 px-3 py-2"
        />
        <button
          type="submit"
          disabled={mutation.isPending}
          className="inline-flex items-center justify-center rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/85 disabled:opacity-50"
        >
          {mutation.isPending ? "Subscribing…" : "Subscribe"}
        </button>
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
  avatar,
}: {
  channel: SubscribedChannel;
  avatar: boolean;
}) {
  const invalidate = useInvalidateChannels();
  const update = useMutation({
    mutationFn: (prefs: Omit<ChannelPrefsUpdate, "channelId">) =>
      updatePrefs({ data: { channelId: channel.channel_id, ...prefs } }),
    onSettled: invalidate,
  });
  const remove = useMutation({
    mutationFn: () => unsubscribe({ data: { channelId: channel.channel_id } }),
    onSettled: invalidate,
  });
  const busy = update.isPending || remove.isPending;
  const priorId = `prior-${channel.channel_id}`;

  return (
    <li className="flex flex-wrap items-center gap-x-6 gap-y-2 py-3">
      <div className="flex min-w-48 flex-1 items-center gap-3">
        {avatar && channel.thumbnail_url && (
          <img
            src={channel.thumbnail_url}
            alt=""
            width={40}
            height={40}
            className="size-10 shrink-0 rounded-full outline outline-1 -outline-offset-1 outline-black/10 dark:outline-white/10"
          />
        )}
        <div className="min-w-0">
          <p className="truncate font-medium">{channel.title}</p>
          {channel.handle && (
            <p className="truncate text-sm text-muted-foreground">
              {channel.handle}
            </p>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <label htmlFor={priorId} className="text-sm">
          Prior
        </label>
        <select
          id={priorId}
          value={channel.prior}
          disabled={busy}
          onChange={(event) =>
            update.mutate({ prior: event.target.value as Prior })
          }
          className="rounded-lg border border-input bg-transparent outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 px-2 py-1"
        >
          {PRIORS.map((prior) => (
            <option key={prior} value={prior}>
              {PRIOR_LABELS[prior]}
            </option>
          ))}
        </select>
      </div>
      <label className="flex items-center gap-1 text-sm">
        <input
          type="checkbox"
          checked={channel.pinned}
          disabled={busy}
          onChange={(event) => update.mutate({ pinned: event.target.checked })}
        />
        Pinned
      </label>
      <label className="flex items-center gap-1 text-sm">
        <input
          type="checkbox"
          checked={channel.muted}
          disabled={busy}
          onChange={(event) => update.mutate({ muted: event.target.checked })}
        />
        Muted
      </label>
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          if (window.confirm(`Unsubscribe from ${channel.title}?`)) {
            remove.mutate();
          }
        }}
        className="text-sm text-destructive underline disabled:opacity-50"
      >
        Unsubscribe
      </button>
      {(update.isError || remove.isError) && (
        <p role="alert" className="w-full text-sm text-destructive">
          Couldn't save that change. Try again.
        </p>
      )}
    </li>
  );
}
