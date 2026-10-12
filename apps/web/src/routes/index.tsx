import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

import { AppHeader } from "#/components/AppHeader";
import { DisplayToggles } from "#/components/DisplayToggles";
import { FeedError } from "#/components/FeedError";
import { FeedHistory } from "#/components/FeedHistory";
import { FeedList } from "#/components/FeedList";
import { RefreshFeedButton } from "#/components/RefreshFeedButton";
import { formatFeedDate } from "#/lib/format";
import { displayPrefsQuery } from "#/server/display";
import { feedHistoryQuery, todayFeedQuery } from "#/server/feeds";

export const Route = createFileRoute("/")({
  loader: ({ context: { queryClient } }) =>
    Promise.all([
      queryClient.ensureQueryData(todayFeedQuery),
      queryClient.ensureQueryData(feedHistoryQuery),
      queryClient.ensureQueryData(displayPrefsQuery),
    ]),
  component: Home,
  errorComponent: FeedError,
});

function Home() {
  const { data: feed } = useSuspenseQuery(todayFeedQuery);
  const { data: display } = useSuspenseQuery(displayPrefsQuery);

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <AppHeader />
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <h2 className="text-xl font-semibold">
          Today{feed && ` · ${formatFeedDate(feed.date)}`}
        </h2>
        <DisplayToggles />
      </div>
      {feed ? (
        <>
          <FeedList feed={feed} display={display} />
          <RefreshFeedButton />
        </>
      ) : (
        <div className="flex flex-col items-start gap-3 rounded border border-dashed p-6">
          <p className="font-medium">There's no feed for today yet.</p>
          <p className="text-gray-600">
            The feed is built once a day from your subscriptions. Build it now,
            or subscribe to channels on the curation page first.
          </p>
          <RefreshFeedButton label="Build today's feed" />
        </div>
      )}
      <FeedHistory />
    </main>
  );
}
