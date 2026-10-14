import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute, redirect } from "@tanstack/react-router";

import { AppShell } from "#/components/AppShell";
import { FeedError } from "#/components/FeedError";
import { FeedList } from "#/components/FeedList";
import { RefreshFeedButton } from "#/components/RefreshFeedButton";
import { formatFeedDate } from "#/lib/format";
import { todayFeedQuery } from "#/server/feeds";
import { onboardingQuery } from "#/server/onboarding";

export const Route = createFileRoute("/")({
  loader: async ({ context: { queryClient } }) => {
    // A fresh install has nothing to show: set it up first. Only here, so other
    // pages stay reachable.
    const onboarding = await queryClient.fetchQuery(onboardingQuery);
    if (onboarding.needed) throw redirect({ to: "/welcome" });
    await queryClient.ensureQueryData(todayFeedQuery);
  },
  component: Home,
  errorComponent: FeedError,
});

function Home() {
  const { data: feed } = useSuspenseQuery(todayFeedQuery);

  return (
    <AppShell
      className="flex max-w-[110rem] flex-col gap-2"
      actions={
        feed && (
          <div className="mr-1 flex items-center gap-3">
            <time
              dateTime={feed.date}
              className="hidden text-sm text-muted-foreground md:block"
            >
              {formatFeedDate(feed.date)}
            </time>
            <RefreshFeedButton variant="secondary" compact />
          </div>
        )
      }
    >
      <h2 className="sr-only">
        Today{feed && `, ${formatFeedDate(feed.date)}`}
      </h2>
      {feed ? (
        <FeedList feed={feed} dismissible />
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
    </AppShell>
  );
}
