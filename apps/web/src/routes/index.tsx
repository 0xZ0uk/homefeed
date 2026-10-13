import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

import { AppShell } from "#/components/AppShell";
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
    <AppShell className="flex max-w-[110rem] flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 pt-2">
        <h2 className="text-xl font-bold">
          Today
          {feed && (
            <span className="ml-2 text-base font-normal text-muted-foreground">
              {formatFeedDate(feed.date)}
            </span>
          )}
        </h2>
        {feed && <RefreshFeedButton variant="secondary" />}
      </div>
      {feed ? (
        <FeedList feed={feed} display={display} dismissible />
      ) : (
        <div className="mx-auto my-16 flex max-w-md flex-col items-center gap-3 text-center">
          <p className="text-lg font-medium">There's no feed for today yet.</p>
          <p className="text-muted-foreground">
            The feed is built once a day from your subscriptions. Build it now,
            or subscribe to channels on the curation page first.
          </p>
          <RefreshFeedButton label="Build today's feed" />
        </div>
      )}
      <footer className="mt-12 flex flex-col gap-6 border-t pt-6">
        <DisplayToggles />
        <FeedHistory />
      </footer>
    </AppShell>
  );
}
