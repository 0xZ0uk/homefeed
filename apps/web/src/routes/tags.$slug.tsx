import {
  useQueryErrorResetBoundary,
  useSuspenseQuery,
} from "@tanstack/react-query";
import {
  Link,
  createFileRoute,
  notFound,
  redirect,
  useRouter,
  type ErrorComponentProps,
} from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";

import { AppShell } from "#/components/AppShell";
import { SubscribeTag } from "#/components/SubscribeTag";
import { VideoCard } from "#/components/VideoCard";
import {
  describeVideoCount,
  isTagSlug,
  pageCount,
  parseTagParams,
  type TagParams,
} from "#/lib/tags";
import { tagQuery } from "#/server/tags";

/**
 * One tag: its label and a paginated grid of every known video carrying it,
 * newest first, in the feed's card style (watched ones greyed out). An alias
 * redirects to the tag's own slug. The tag can be subscribed to, which boosts
 * its videos in the home feed.
 */
export const Route = createFileRoute("/tags/$slug")({
  validateSearch: (search: Record<string, unknown>): TagParams =>
    parseTagParams(search),
  loaderDeps: ({ search }) => search,
  loader: async ({ params, deps, context: { queryClient } }) => {
    if (!isTagSlug(params.slug)) throw notFound();
    const detail = await queryClient.ensureQueryData(
      tagQuery(params.slug, deps),
    );
    if (!detail) throw notFound();
    if (detail.tag.slug !== params.slug) {
      throw redirect({
        to: "/tags/$slug",
        params: { slug: detail.tag.slug },
        search: deps,
        replace: true,
      });
    }
    return { label: detail.tag.label };
  },
  head: ({ loaderData }) => ({
    meta: [
      {
        title: loaderData
          ? `${loaderData.label} · Tags · Homefeed`
          : "Tag · Homefeed",
      },
    ],
  }),
  component: TagPage,
  errorComponent: TagError,
  notFoundComponent: () => (
    <Shell>
      <p>
        There's no such tag. <BackToFeed />
      </p>
    </Shell>
  ),
});

function TagPage() {
  const { slug } = Route.useParams();
  const params = Route.useSearch();
  const { data: detail } = useSuspenseQuery(tagQuery(slug, params));
  // One "now" per render pass keeps every card's age consistent.
  const [now] = useState(() => new Date());
  if (!detail) return null; // the loader already threw notFound

  const { tag, videos } = detail;
  const page = params.page ?? 1;
  const pages = pageCount(tag.video_count);

  return (
    <Shell>
      <div className="flex flex-col gap-1 pt-2">
        <h1 className="text-xl font-bold break-words">{tag.label}</h1>
        <p className="text-sm text-muted-foreground">
          {describeVideoCount(tag.video_count)}
        </p>
        <SubscribeTag detail={detail} />
      </div>
      <h2 className="sr-only">Videos</h2>
      {videos.length === 0 ? (
        <p className="py-16 text-center text-muted-foreground">
          {page > 1
            ? "No more videos with this tag."
            : "No videos carry this tag yet."}
        </p>
      ) : (
        <ol
          aria-label="Videos"
          className="grid grid-cols-1 gap-x-4 gap-y-10 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4"
        >
          {videos.map((video) => (
            <VideoCard key={video.video_id} video={video} now={now} />
          ))}
        </ol>
      )}
      {(page > 1 || page < pages) && (
        <nav aria-label="Tag pages" className="flex items-center gap-4 text-sm">
          {page > 1 && (
            <Link
              to="/tags/$slug"
              params={{ slug: tag.slug }}
              search={parseTagParams({ page: page - 1 })}
              className="underline"
            >
              Newer
            </Link>
          )}
          <span className="text-muted-foreground">
            Page {page} of {pages}
          </span>
          {page < pages && (
            <Link
              to="/tags/$slug"
              params={{ slug: tag.slug }}
              search={parseTagParams({ page: page + 1 })}
              className="underline"
            >
              Older
            </Link>
          )}
        </nav>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <AppShell className="flex max-w-[110rem] flex-col gap-4">
      {children}
    </AppShell>
  );
}

function BackToFeed() {
  return (
    <Link to="/" className="underline">
      Back to the feed
    </Link>
  );
}

function TagError({ error }: ErrorComponentProps) {
  const router = useRouter();
  const queryErrorResetBoundary = useQueryErrorResetBoundary();

  useEffect(() => {
    queryErrorResetBoundary.reset();
  }, [queryErrorResetBoundary]);

  return (
    <Shell>
      <div role="alert" className="flex flex-col items-start gap-3">
        <p>
          Couldn't load this tag
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
    </Shell>
  );
}
