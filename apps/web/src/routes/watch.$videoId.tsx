import {
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
import { Chapters } from "#/components/Chapters";
import { PlayerMediaProvider } from "#/components/PlayerMedia";
import { SaveToPlaylist } from "#/components/SaveToPlaylist";
import { SimilarVideos } from "#/components/SimilarVideos";
import { SubscribeChannel } from "#/components/SubscribeChannel";
import { VideoTags } from "#/components/VideoTags";
import { WatchAndRate } from "#/components/WatchAndRate";
import { NextInQueue } from "#/components/NextInQueue";
import { QueueButton } from "#/components/QueueButton";
import { formatDuration, formatFeedDate } from "#/lib/format";
import { cn } from "#/lib/utils";
import { isVideoId } from "#/lib/ids";
import { fetchResumePosition } from "#/server/history";
import { ratingQuery } from "#/server/ratings";
import { videoQuery } from "#/server/videos";

/**
 * The watch page: the player and the rating (prompted when the video ends,
 * editable any time), then title, tags, channel, description and a "More like
 * this" button, with chapters and the queue beside them. SponsorBlock segments
 * are marked on the progress bar and skipped. It never autoplays and suggests
 * nothing when the video ends: similar videos show only when asked for. It
 * picks up where the last visit stopped (see `fetchResumePosition`).
 */
export const Route = createFileRoute("/watch/$videoId")({
  loader: async ({ params, context: { queryClient } }) => {
    if (!isVideoId(params.videoId)) throw notFound();
    // Not awaited: a missing rating shouldn't hold up (or fail) the page.
    void queryClient.prefetchQuery(ratingQuery(params.videoId));
    const [video, resumeAt] = await Promise.all([
      queryClient.ensureQueryData(videoQuery(params.videoId)),
      // Fresh on every visit (not cached): it's where the last one stopped.
      fetchResumePosition({ data: { videoId: params.videoId } }).catch(
        () => null,
      ),
    ]);
    if (!video) throw notFound();
    return { title: video.title, resumeAt };
  },
  head: ({ loaderData }) => ({
    meta: [
      {
        title: loaderData
          ? `${loaderData.title} · Homefeed`
          : "Watch · Homefeed",
      },
    ],
  }),
  component: Watch,
  errorComponent: WatchError,
  notFoundComponent: () => (
    <WatchShell>
      <div className="flex flex-col items-start gap-3">
        <h1 className="text-xl font-bold">Video not found</h1>
        <p>
          This video doesn't exist or can't be watched. <BackToFeed />
        </p>
      </div>
    </WatchShell>
  ),
});

function Watch() {
  const { videoId } = Route.useParams();
  const { data: video } = useSuspenseQuery(videoQuery(videoId));
  const { resumeAt } = Route.useLoaderData();
  if (!video) return null; // the loader already threw notFound

  const duration = formatDuration(video.duration_seconds);
  const published = formatFeedDate(video.published_at?.slice(0, 10) ?? "");

  return (
    <WatchShell bare>
      <WatchAndRate
        key={video.id}
        videoId={video.id}
        poster={video.thumbnail_url}
        startAt={resumeAt}
        chapters={video.chapters}
        contentClassName={CONTENT_CLASS}
        aside={
          <aside className="flex min-w-0 flex-col gap-4">
            <NextInQueue videoId={video.id} />
            <Chapters chapters={video.chapters} />
          </aside>
        }
      >
        <div className="flex flex-col gap-2">
          <h1 className="text-xl leading-tight font-bold">{video.title}</h1>
          <VideoTags videoId={video.id} tags={video.tags} />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
          <div className="flex min-w-0 items-center gap-3">
            <ChannelAvatar
              url={video.channel_thumbnail_url}
              title={video.channel_title}
            />
            <p className="flex min-w-0 flex-col">
              <Link
                to="/channels/$channelId"
                params={{ channelId: video.channel_id }}
                className="truncate font-medium hover:underline"
              >
                {video.channel_title}
              </Link>
              {video.channel_handle && (
                <span className="truncate text-xs text-muted-foreground">
                  {video.channel_handle}
                </span>
              )}
            </p>
            <SubscribeChannel channelId={video.channel_id} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <QueueButton videoId={video.id} title={video.title} />
            <SaveToPlaylist videoId={video.id} />
          </div>
        </div>
        <Description
          meta={[duration, video.published_at && published].filter(
            (part): part is string => Boolean(part),
          )}
          stale={video.is_stale}
          text={video.description}
        />
        <SimilarVideos key={video.id} videoId={video.id} />
      </WatchAndRate>
    </WatchShell>
  );
}

/** YouTube's description box: details on top, the text clamped until
 * expanded. */
function Description({
  meta,
  stale,
  text,
}: {
  meta: string[];
  stale: boolean;
  text: string | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const long = (text?.length ?? 0) > 280 || (text?.split("\n").length ?? 0) > 3;

  return (
    <div className="flex flex-col gap-1 rounded-xl bg-secondary p-3 text-sm">
      {meta.length > 0 && <p className="font-medium">{meta.join(" · ")}</p>}
      {stale && (
        <p className="text-muted-foreground">
          YouTube couldn't be reached; showing saved details.
        </p>
      )}
      {text && (
        <p
          className={cn(
            "break-words whitespace-pre-line",
            long && !expanded && "line-clamp-3",
          )}
        >
          {text}
        </p>
      )}
      {long && (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
          className="self-start font-medium hover:underline"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

/** The padded, centered content area below the player (and the whole page for
 * the not-found and error states). */
const CONTENT_CLASS =
  "mx-auto grid w-full max-w-6xl gap-6 px-4 pt-4 pb-24 sm:px-6 has-[>aside>*]:max-w-[110rem] xl:has-[>aside>*]:grid-cols-[minmax(0,1fr)_24rem]";

/** `bare` leaves the content to span edge to edge (the player band); the
 * children then pad themselves with `CONTENT_CLASS`. */
function WatchShell({
  children,
  bare,
}: {
  children: ReactNode;
  bare?: boolean;
}) {
  return (
    <AppShell guide="drawer" className="max-w-none px-0 pt-0 pb-0 sm:px-0">
      <PlayerMediaProvider>
        {bare ? children : <div className={CONTENT_CLASS}>{children}</div>}
      </PlayerMediaProvider>
    </AppShell>
  );
}

function BackToFeed() {
  return (
    <Link to="/" className="underline">
      Back to today's feed
    </Link>
  );
}

function WatchError({ error }: ErrorComponentProps) {
  const router = useRouter();
  const queryErrorResetBoundary = useQueryErrorResetBoundary();

  useEffect(() => {
    queryErrorResetBoundary.reset();
  }, [queryErrorResetBoundary]);

  return (
    <WatchShell>
      <div role="alert" className="flex flex-col items-start gap-3">
        <h1 className="text-xl font-bold">Couldn't load this video</h1>
        {error instanceof Error && error.message && <p>{error.message}.</p>}
        <button
          type="button"
          onClick={() => void router.invalidate()}
          className="underline"
        >
          Try again
        </button>
        <BackToFeed />
      </div>
    </WatchShell>
  );
}
