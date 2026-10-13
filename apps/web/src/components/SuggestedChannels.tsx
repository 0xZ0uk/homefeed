import {
  useMutation,
  useQuery,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { channelUrl, featuredByText, formatSubscribers } from "#/lib/discover";
import { showsImages } from "#/lib/display";
import { formatAge, formatDuration } from "#/lib/format";
import { channelsQuery, subscribe } from "#/server/channels";
import {
  channelUploadsQuery,
  suggestedChannelsQuery,
  type SuggestedChannel,
} from "#/server/discover";
import { displayPrefsQuery } from "#/server/display";

/** Channels featured by channels I like, each with a subscribe action. */
export function SuggestedChannels() {
  const { data: suggestions } = useSuspenseQuery(suggestedChannelsQuery);
  const { data: display } = useSuspenseQuery(displayPrefsQuery);
  const [status, setStatus] = useState<string | null>(null);
  const avatars = showsImages(display);

  return (
    <section
      aria-labelledby="suggested-heading"
      className="flex flex-col gap-3"
    >
      <div className="flex flex-col gap-1">
        <h2 id="suggested-heading" className="text-xl font-semibold">
          Suggested channels
        </h2>
        <p className="text-muted-foreground">
          Channels featured by the channels you love or like, and by channels of
          videos you rated A-- or higher.
        </p>
      </div>
      <p role="status" className="min-h-6">
        {status}
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
              avatar={avatars}
              onStatus={setStatus}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function SuggestionRow({
  channel,
  avatar,
  onStatus,
}: {
  channel: SuggestedChannel;
  avatar: boolean;
  onStatus: (message: string) => void;
}) {
  const queryClient = useQueryClient();
  const [showUploads, setShowUploads] = useState(false);
  const mutation = useMutation({
    mutationFn: () =>
      subscribe({ data: { url: channelUrl(channel.channel_id) } }),
    onSuccess: async (result) => {
      if (!result.ok) return;
      onStatus(`Subscribed to ${result.channel.title}.`);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: suggestedChannelsQuery.queryKey,
        }),
        queryClient.invalidateQueries({ queryKey: channelsQuery.queryKey }),
      ]);
    },
  });
  const failed =
    mutation.isError || (mutation.data !== undefined && !mutation.data.ok);
  const subscribers = formatSubscribers(channel.subscriber_count);
  const uploadsId = `uploads-${channel.channel_id}`;

  return (
    <li className="flex flex-col gap-2 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex min-w-48 flex-1 items-center gap-3">
          {avatar && channel.thumbnail_url && (
            <img
              src={channel.thumbnail_url}
              alt=""
              width={40}
              height={40}
              loading="lazy"
              className="size-10 shrink-0 rounded-full"
            />
          )}
          <div className="min-w-0">
            <p className="truncate font-medium">{channel.title}</p>
            <p className="truncate text-sm text-muted-foreground">
              {[channel.handle, subscribers].filter(Boolean).join(" · ")}
            </p>
            <p className="text-sm text-muted-foreground">
              {featuredByText(channel.featured_by)}
            </p>
          </div>
        </div>
        <button
          type="button"
          aria-expanded={showUploads}
          aria-controls={uploadsId}
          onClick={() => setShowUploads((shown) => !shown)}
          className="text-sm underline"
        >
          {showUploads ? "Hide uploads" : "Recent uploads"}
        </button>
        <button
          type="button"
          disabled={mutation.isPending}
          onClick={() => mutation.mutate()}
          className="inline-flex items-center justify-center rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/85 disabled:opacity-50"
        >
          {mutation.isPending ? "Subscribing…" : "Subscribe"}
        </button>
      </div>
      {failed && (
        <p role="alert" className="text-sm text-destructive">
          {mutation.data && !mutation.data.ok
            ? mutation.data.message
            : "Couldn't subscribe. Try again later."}
        </p>
      )}
      {showUploads && (
        <div id={uploadsId}>
          <UploadsPreview channelId={channel.channel_id} />
        </div>
      )}
    </li>
  );
}

function UploadsPreview({ channelId }: { channelId: string }) {
  const { data, isPending, isError } = useQuery(channelUploadsQuery(channelId));

  if (isPending) {
    return <p className="text-sm text-muted-foreground">Loading uploads…</p>;
  }
  if (isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        Couldn't load this channel's uploads. Try again later.
      </p>
    );
  }
  if (data.videos.length === 0) {
    return <p className="text-sm text-muted-foreground">No uploads.</p>;
  }
  return (
    <ul
      className="flex flex-col gap-1 pl-4 text-sm"
      aria-label="Recent uploads"
    >
      {data.videos.map((video) => {
        const details = [
          formatDuration(video.duration_seconds),
          formatAge(video.published_at),
        ].filter(Boolean);
        return (
          <li key={video.id}>
            <Link
              to="/watch/$videoId"
              params={{ videoId: video.id }}
              className="hover:underline"
            >
              {video.title}
            </Link>
            {details.length > 0 && (
              <span className="text-muted-foreground tabular-nums">
                {" "}
                · {details.join(" · ")}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
