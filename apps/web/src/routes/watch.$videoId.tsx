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
import { useEffect, type ReactNode } from "react";

import { AppHeader } from "#/components/AppHeader";
import { Chapters } from "#/components/Chapters";
import { Comments } from "#/components/Comments";
import { PlayerMediaProvider } from "#/components/PlayerMedia";
import { SaveToPlaylist } from "#/components/SaveToPlaylist";
import { SponsorSkip } from "#/components/SponsorSkip";
import { WatchAndRate } from "#/components/WatchAndRate";
import { WatchQueueControls } from "#/components/WatchQueueControls";
import { formatDuration } from "#/lib/format";
import { showsImages } from "#/lib/display";
import { isVideoId } from "#/lib/ids";
import { displayPrefsQuery } from "#/server/display";
import { fetchResumePosition } from "#/server/history";
import { ratingQuery } from "#/server/ratings";
import { videoQuery } from "#/server/videos";

/**
 * The watch page: the player and the rating (prompted when the video ends or
 * when leaving, editable any time), then title, channel, description,
 * chapters and comments (loaded only on demand). SponsorBlock segments are
 * skipped. It never autoplays and suggests nothing when the video ends. It
 * picks up where the last visit stopped (see `fetchResumePosition`).
 */
export const Route = createFileRoute("/watch/$videoId")({
  loader: async ({ params, context: { queryClient } }) => {
    if (!isVideoId(params.videoId)) throw notFound();
    // Not awaited: a missing rating shouldn't hold up (or fail) the page.
    void queryClient.prefetchQuery(ratingQuery(params.videoId));
    const [video, , resumeAt] = await Promise.all([
      queryClient.ensureQueryData(videoQuery(params.videoId)),
      queryClient.ensureQueryData(displayPrefsQuery),
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
      <p>
        This video doesn't exist or can't be watched. <BackToFeed />
      </p>
    </WatchShell>
  ),
});

function Watch() {
  const { videoId } = Route.useParams();
  const { data: video } = useSuspenseQuery(videoQuery(videoId));
  const { data: display } = useSuspenseQuery(displayPrefsQuery);
  const { resumeAt } = Route.useLoaderData();
  if (!video) return null; // the loader already threw notFound

  return (
    <WatchShell>
      <WatchAndRate
        key={video.id}
        videoId={video.id}
        poster={showsImages(display) ? video.thumbnail_url : null}
        startAt={resumeAt}
      />
      <SponsorSkip videoId={video.id} />
      <article className="flex flex-col gap-3">
        <h2 className="text-2xl font-semibold">{video.title}</h2>
        <p className="text-gray-700">
          {video.channel_title}
          {video.channel_handle && (
            <span className="text-gray-500"> {video.channel_handle}</span>
          )}
          {video.duration_seconds != null && (
            <span className="text-gray-500">
              {" · "}
              {formatDuration(video.duration_seconds)}
            </span>
          )}
        </p>
        <WatchQueueControls videoId={video.id} title={video.title} />
        <SaveToPlaylist videoId={video.id} />
        {video.is_stale && (
          <p className="text-sm text-gray-500">
            YouTube couldn't be reached; showing saved details.
          </p>
        )}
        {video.description && (
          <p className="whitespace-pre-line break-words text-gray-800">
            {video.description}
          </p>
        )}
        <Chapters chapters={video.chapters} />
        <Comments videoId={video.id} />
      </article>
    </WatchShell>
  );
}

function WatchShell({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-6 p-8">
      <AppHeader />
      <PlayerMediaProvider>{children}</PlayerMediaProvider>
    </main>
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
        <p>
          Couldn't load this video
          {error instanceof Error && error.message ? `: ${error.message}` : ""}.
        </p>
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
