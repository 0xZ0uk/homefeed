import {
  useMutation,
  useQueryClient,
  useQueryErrorResetBoundary,
  useSuspenseQuery,
} from "@tanstack/react-query";
import {
  Link,
  createFileRoute,
  notFound,
  useRouter,
  type ErrorComponentProps,
} from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";

import { AppShell } from "#/components/AppShell";
import { ChannelAvatar } from "#/components/ChannelAvatar";
import { VideoCard } from "#/components/VideoCard";
import { Button } from "#/components/ui/button";
import { channelUrl, formatSubscribers, isChannelId } from "#/lib/discover";
import { cn } from "#/lib/utils";
import { channelsQuery, subscribe } from "#/server/channels";
import { channelHidesQuery, hide, unhide } from "#/server/channel-hides";
import {
  channelProfileQuery,
  suggestedChannelsQuery,
  type ChannelProfileOut,
} from "#/server/discover";

/** One channel: banner, who it is, subscribe / hide actions and its latest videos. */
export const Route = createFileRoute("/channels/$channelId")({
  loader: async ({ params, context: { queryClient } }) => {
    if (!isChannelId(params.channelId)) throw notFound();
    const profile = await queryClient.ensureQueryData(
      channelProfileQuery(params.channelId),
    );
    if (!profile) throw notFound();
    return { title: profile.title };
  },
  head: ({ loaderData }) => ({
    meta: [
      {
        title: loaderData
          ? `${loaderData.title} · Homefeed`
          : "Channel · Homefeed",
      },
    ],
  }),
  component: ChannelPage,
  errorComponent: ChannelError,
  notFoundComponent: () => (
    <Shell>
      <p>
        There's no such channel. <BackToDiscover />
      </p>
    </Shell>
  ),
});

function ChannelPage() {
  const { channelId } = Route.useParams();
  const { data: profile } = useSuspenseQuery(channelProfileQuery(channelId));
  const [now] = useState(() => new Date());
  if (!profile) return null; // the loader already threw notFound

  return (
    <Shell>
      {profile.banner_url && (
        <img
          src={profile.banner_url}
          alt=""
          referrerPolicy="no-referrer"
          className="aspect-[6/1] min-h-20 w-full rounded-xl bg-secondary object-cover"
        />
      )}
      <Header profile={profile} />
      <section aria-labelledby="latest-heading" className="flex flex-col gap-4">
        <h3 id="latest-heading" className="text-lg font-semibold">
          Latest videos
        </h3>
        {profile.videos.length === 0 ? (
          <p className="text-muted-foreground">No videos to show.</p>
        ) : (
          <ol
            aria-label="Latest videos"
            className="grid grid-cols-1 gap-x-4 gap-y-10 sm:grid-cols-2 lg:grid-cols-3"
          >
            {profile.videos.map((video) => (
              <VideoCard
                key={video.id}
                now={now}
                video={{
                  video_id: video.id,
                  title: video.title,
                  duration_seconds: video.duration_seconds,
                  published_at: video.published_at,
                  thumbnail_url: video.thumbnail_url,
                  view_count: video.view_count,
                  channel_id: profile.channel_id,
                  channel_title: profile.title,
                  channel_thumbnail_url: profile.thumbnail_url,
                  watched: false,
                }}
              />
            ))}
          </ol>
        )}
      </section>
    </Shell>
  );
}

function Header({ profile }: { profile: ChannelProfileOut }) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const invalidate = () =>
    Promise.all([
      queryClient.invalidateQueries({
        queryKey: channelProfileQuery(profile.channel_id).queryKey,
      }),
      queryClient.invalidateQueries({
        queryKey: suggestedChannelsQuery.queryKey,
      }),
      queryClient.invalidateQueries({ queryKey: channelsQuery.queryKey }),
      queryClient.invalidateQueries({ queryKey: channelHidesQuery.queryKey }),
    ]);
  const subscribing = useMutation({
    mutationFn: () =>
      subscribe({ data: { url: channelUrl(profile.channel_id) } }),
    onSuccess: async (result) => {
      if (result.ok) await invalidate();
    },
  });
  const hiding = useMutation({
    mutationFn: () =>
      hide({ data: { channelId: profile.channel_id, kind: "blocked" } }),
    onSuccess: invalidate,
  });
  const restoring = useMutation({
    mutationFn: () => unhide({ data: { channelId: profile.channel_id } }),
    onSuccess: invalidate,
  });
  const busy = subscribing.isPending || hiding.isPending || restoring.isPending;
  const subscribeFailed =
    subscribing.isError ||
    (subscribing.data !== undefined && !subscribing.data.ok);
  const meta = [profile.handle, formatSubscribers(profile.subscriber_count)]
    .filter(Boolean)
    .join(" · ");
  const description = profile.description?.trim();
  const blocked = profile.hidden === "blocked";

  return (
    <div className="flex flex-wrap items-start gap-x-6 gap-y-4">
      <ChannelAvatar
        url={profile.thumbnail_url}
        title={profile.title}
        className="size-20 text-3xl sm:size-28 sm:text-4xl [&_[data-slot=avatar-fallback]]:text-3xl"
      />
      <div className="flex min-w-64 flex-1 flex-col gap-2">
        <h2 className="text-2xl font-bold break-words">{profile.title}</h2>
        {meta && <p className="text-muted-foreground">{meta}</p>}
        {description && (
          <div className="flex max-w-prose flex-col items-start gap-1">
            <p
              className={cn(
                "text-sm whitespace-pre-line text-muted-foreground",
                !expanded && "line-clamp-3",
              )}
            >
              {description}
            </p>
            {description.length > 160 && (
              <button
                type="button"
                aria-expanded={expanded}
                onClick={() => setExpanded((open) => !open)}
                className="text-sm font-medium underline"
              >
                {expanded ? "Show less" : "more"}
              </button>
            )}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          {profile.subscribed ? (
            <Button size="lg" className="px-4" disabled>
              Subscribed
            </Button>
          ) : (
            <Button
              size="lg"
              className="px-4"
              disabled={busy}
              onClick={() => subscribing.mutate()}
            >
              {subscribing.isPending ? "Subscribing…" : "Subscribe"}
            </Button>
          )}
          {blocked ? (
            <>
              <span className="text-sm text-muted-foreground">
                Hidden from feed
              </span>
              <Button
                variant="secondary"
                size="lg"
                className="px-4"
                disabled={busy}
                onClick={() => restoring.mutate()}
              >
                {restoring.isPending ? "Restoring…" : "Show again"}
              </Button>
            </>
          ) : (
            <Button
              variant="secondary"
              size="lg"
              className="px-4"
              disabled={busy}
              onClick={() => hiding.mutate()}
            >
              {hiding.isPending ? "Hiding…" : "Don't show"}
            </Button>
          )}
        </div>
        {subscribeFailed && (
          <p role="alert" className="text-sm text-destructive">
            {subscribing.data && !subscribing.data.ok
              ? subscribing.data.message
              : "Couldn't subscribe. Try again later."}
          </p>
        )}
        {(hiding.isError || restoring.isError) && (
          <p role="alert" className="text-sm text-destructive">
            Couldn't update this channel. Try again later.
          </p>
        )}
      </div>
    </div>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <AppShell className="flex max-w-6xl flex-col gap-6">{children}</AppShell>
  );
}

function BackToDiscover() {
  return (
    <Link to="/discover" className="underline">
      Back to Discover
    </Link>
  );
}

function ChannelError({ error }: ErrorComponentProps) {
  const router = useRouter();
  const queryErrorResetBoundary = useQueryErrorResetBoundary();

  useEffect(() => {
    queryErrorResetBoundary.reset();
  }, [queryErrorResetBoundary]);

  return (
    <Shell>
      <div role="alert" className="flex flex-col items-start gap-3">
        <p>
          Couldn't load this channel
          {error instanceof Error && error.message ? `: ${error.message}` : ""}.
        </p>
        <button
          type="button"
          onClick={() => void router.invalidate()}
          className="underline"
        >
          Try again
        </button>
        <BackToDiscover />
      </div>
    </Shell>
  );
}
