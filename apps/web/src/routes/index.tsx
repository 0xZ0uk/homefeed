import { useSuspenseQuery, type QueryClient } from "@tanstack/react-query";
import { createFileRoute, redirect } from "@tanstack/react-router";

import { AppShell } from "#/components/AppShell";
import { DiscoveryCarousel } from "#/components/DiscoveryCarousel";
import { FeedError } from "#/components/FeedError";
import { FeedList } from "#/components/FeedList";
import { MixStrip } from "#/components/MixStrip";
import { NoFeedYet } from "#/components/NoFeedYet";
import { RefreshFeedButton } from "#/components/RefreshFeedButton";
import { formatFeedDate } from "#/lib/format";
import { previousFeedOf } from "#/lib/today";
import { discoveryVideosQuery } from "#/server/discover";
import { feedListQuery, feedQuery, todayFeedQuery } from "#/server/feeds";
import { onboardingQuery } from "#/server/onboarding";
import { settingsQuery } from "#/server/settings";

export const Route = createFileRoute("/")({
  loader: async ({ context: { queryClient } }) => {
    // A fresh install has nothing to show: set it up first. Only here, so other
    // pages stay reachable.
    const onboarding = await queryClient.fetchQuery(onboardingQuery);
    if (onboarding.needed) throw redirect({ to: "/welcome" });
    // What comes besides the feed (Discovery, the mix, what's left of the last
    // feed) is extra: it doesn't hold up or break the page (see
    // DiscoveryCarousel).
    const [feed] = await Promise.all([
      queryClient.ensureQueryData(todayFeedQuery),
      queryClient.prefetchQuery(discoveryVideosQuery),
      queryClient.prefetchQuery(settingsQuery),
    ]);
    if (!feed || feed.items.length === 0) await prefetchLeftovers(queryClient);
  },
  component: Home,
  errorComponent: FeedError,
});

/** Load the last feed that picked anything, for the page without a feed. */
async function prefetchLeftovers(queryClient: QueryClient) {
  try {
    const feeds = await queryClient.fetchQuery(feedListQuery);
    const previous = previousFeedOf(feeds);
    if (previous) await queryClient.prefetchQuery(feedQuery(previous.date));
  } catch {
    // Left out: the page is whole without it.
  }
}

/**
 * Today: the day's feed in two lanes (see `FeedList`), with the topics it's
 * about and the dial to steer the next one under the header (see `MixStrip`),
 * and the Discovery carousel at the top of "New to you". With no feed yet it's
 * still a page worth opening (see `NoFeedYet`).
 */
function Home() {
  const { data: feed } = useSuspenseQuery(todayFeedQuery);

  return (
    <AppShell
      className="flex max-w-[110rem] flex-col gap-2"
      actions={
        feed && (
          <div className="mr-1">
            <RefreshFeedButton variant="secondary" compact />
          </div>
        )
      }
    >
      <h1 className="pt-2 text-xl font-semibold">
        Today
        {feed && (
          <>
            {/* Read as "Today, Thu, Oct 15, 2026". */}
            <span className="sr-only">, </span>
            <time
              dateTime={feed.date}
              className="ml-3 text-sm font-normal text-muted-foreground"
            >
              {formatFeedDate(feed.date)}
            </time>
          </>
        )}
      </h1>
      {feed && feed.items.length > 0 ? (
        <>
          <MixStrip feed={feed} />
          <FeedList feed={feed} dismissible shelf={<DiscoveryCarousel />} />
        </>
      ) : (
        <NoFeedYet built={feed !== null} shelf={<DiscoveryCarousel />} />
      )}
    </AppShell>
  );
}
