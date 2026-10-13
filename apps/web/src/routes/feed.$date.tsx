import { useSuspenseQuery } from "@tanstack/react-query";
import { Link, createFileRoute, notFound } from "@tanstack/react-router";

import { AppShell } from "#/components/AppShell";
import { FeedError } from "#/components/FeedError";
import { FeedList } from "#/components/FeedList";
import { formatFeedDate, isFeedDate } from "#/lib/format";
import { feedQuery } from "#/server/feeds";

/** A past (or today's) feed, as it was last built that day. */
export const Route = createFileRoute("/feed/$date")({
  head: ({ params }) => ({
    meta: [{ title: `Feed for ${formatFeedDate(params.date)} · Homefeed` }],
  }),
  loader: ({ params, context: { queryClient } }) => {
    if (!isFeedDate(params.date)) throw notFound();
    return queryClient.ensureQueryData(feedQuery(params.date));
  },
  component: PastFeed,
  errorComponent: FeedError,
  notFoundComponent: () => (
    <AppShell className="flex max-w-4xl flex-col gap-6">
      <p>That isn't a valid date.</p>
    </AppShell>
  ),
});

function PastFeed() {
  const { date } = Route.useParams();
  const { data: feed } = useSuspenseQuery(feedQuery(date));

  return (
    <AppShell className="flex max-w-[110rem] flex-col gap-2">
      <h2 className="pt-2 text-xl font-bold">{formatFeedDate(date)}</h2>
      {feed ? (
        <FeedList feed={feed} />
      ) : (
        <p className="text-muted-foreground">
          No feed was built on this day.{" "}
          <Link to="/" className="underline">
            Go to today's feed
          </Link>
          .
        </p>
      )}
    </AppShell>
  );
}
