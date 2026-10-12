import { useSuspenseQuery } from "@tanstack/react-query";
import { Link, createFileRoute, notFound } from "@tanstack/react-router";

import { AppHeader } from "#/components/AppHeader";
import { DisplayToggles } from "#/components/DisplayToggles";
import { FeedError } from "#/components/FeedError";
import { FeedHistory } from "#/components/FeedHistory";
import { FeedList } from "#/components/FeedList";
import { formatFeedDate, isFeedDate } from "#/lib/format";
import { displayPrefsQuery } from "#/server/display";
import { feedHistoryQuery, feedQuery } from "#/server/feeds";

/** A past (or today's) feed, as it was last built that day. */
export const Route = createFileRoute("/feed/$date")({
  head: ({ params }) => ({
    meta: [{ title: `Feed for ${formatFeedDate(params.date)} · Homefeed` }],
  }),
  loader: ({ params, context: { queryClient } }) => {
    if (!isFeedDate(params.date)) throw notFound();
    return Promise.all([
      queryClient.ensureQueryData(feedQuery(params.date)),
      queryClient.ensureQueryData(feedHistoryQuery),
      queryClient.ensureQueryData(displayPrefsQuery),
    ]);
  },
  component: PastFeed,
  errorComponent: FeedError,
  notFoundComponent: () => (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <AppHeader />
      <p>That isn't a valid date.</p>
    </main>
  ),
});

function PastFeed() {
  const { date } = Route.useParams();
  const { data: feed } = useSuspenseQuery(feedQuery(date));
  const { data: display } = useSuspenseQuery(displayPrefsQuery);

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <AppHeader />
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <h2 className="text-xl font-semibold">{formatFeedDate(date)}</h2>
        <DisplayToggles />
      </div>
      {feed ? (
        <FeedList feed={feed} display={display} />
      ) : (
        <p className="text-gray-600">
          No feed was built on this day.{" "}
          <Link to="/" className="underline">
            Go to today's feed
          </Link>
          .
        </p>
      )}
      <FeedHistory />
    </main>
  );
}
