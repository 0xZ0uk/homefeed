import { useQuery } from "@tanstack/react-query";
import { useId, useState, type ReactNode } from "react";

import { ActionStatusLine, useActionStatus } from "#/components/ActionStatus";
import { FeedCard } from "#/components/FeedCard";
import { openQueue } from "#/components/QueueSheet";
import { RefreshFeedButton } from "#/components/RefreshFeedButton";
import { useFeedActions } from "#/components/use-feed-actions";
import { Button } from "#/components/ui/button";
import {
  leftovers,
  leftoversHeading,
  nextFeedText,
  previousFeedOf,
  queueSummary,
} from "#/lib/today";
import { feedListQuery, feedQuery, type Feed } from "#/server/feeds";
import { queueQuery } from "#/server/queue";
import { settingsQuery } from "#/server/settings";

/**
 * What Today shows when it has no feed to show: none built yet (at 2 a.m., say,
 * before the daily build), or one built with nothing in it (`built`). It is
 * never an empty page: it says when the next feed comes and offers to build
 * it now; shows the extra picks it's given as a `shelf`, such as the Discovery
 * carousel; the picks of the last feed that I haven't watched or dismissed,
 * as ordinary cards; and the queue, with a button to open it.
 */
export function NoFeedYet({
  built = false,
  shelf,
}: {
  built?: boolean;
  shelf?: ReactNode;
}) {
  const headingId = useId();
  // One "now" per render pass, as the feed's cards have.
  const [now] = useState(() => new Date());
  const { data: settings } = useQuery(settingsQuery);
  const { data: feeds } = useQuery(feedListQuery);
  const previous = feeds ? previousFeedOf(feeds) : null;

  return (
    <div className="flex flex-col gap-8 pt-2">
      <section
        aria-labelledby={headingId}
        className="flex max-w-2xl flex-col gap-3"
      >
        <h2 id={headingId} className="text-xl font-bold">
          {built
            ? "The feed for today is empty."
            : "There's no feed for today yet."}
        </h2>
        {settings && (
          <p className="font-medium" suppressHydrationWarning>
            {nextFeedText(
              settings.values.feed_refresh_time,
              now,
              settings.values.timezone ?? settings.system_timezone,
            )}
          </p>
        )}
        <p className="text-muted-foreground">
          {built
            ? "There were no new videos to pick from. Subscribe to more channels on the Subscriptions page, or build the feed again."
            : "The feed is built once a day from your subscriptions. Build it now, or subscribe to channels on the Subscriptions page first."}
        </p>
        <div>
          <RefreshFeedButton
            label={built ? "Rebuild today's feed" : "Build today's feed"}
          />
        </div>
        <QueueNote />
      </section>
      {shelf}
      {previous && <Leftovers date={previous.date} now={now} />}
    </div>
  );
}

/** How many videos are queued, and a button to open the queue. */
function QueueNote() {
  const { data: queue } = useQuery(queueQuery);
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t pt-3">
      <p className="text-sm">
        {queue ? queueSummary(queue.length) : "Your queue"}
      </p>
      <Button
        type="button"
        variant="outline"
        aria-haspopup="dialog"
        onClick={openQueue}
        className="rounded-lg px-3"
      >
        Open queue
      </Button>
    </div>
  );
}

/** The picks of the feed of `date` still to watch, once that feed has loaded. */
function Leftovers({ date, now }: { date: string; now: Date }) {
  const { data: feed } = useQuery(feedQuery(date));
  return feed ? <LeftoverCards feed={feed} now={now} /> : null;
}

/**
 * The picks of an earlier `feed` that I haven't watched or dismissed, as the
 * cards they were in it, with the same actions: they can be dismissed (and
 * brought back) or rated, queued and steered from, with what that did said in
 * a status line under the heading.
 */
function LeftoverCards({ feed, now }: { feed: Feed; now: Date }) {
  const headingId = useId();
  const { status, announce, ref: statusRef } = useActionStatus();
  const actions = useFeedActions(feed, announce);
  const items = leftovers(feed.items);
  const heading = leftoversHeading(feed.date);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <div className="relative">
        <h2 id={headingId} className="text-xl font-bold">
          {heading}
        </h2>
        {/* Hangs under the heading, over the top of the videos. */}
        <ActionStatusLine
          status={status}
          statusRef={statusRef}
          className="absolute top-full left-0 z-20 mt-1 max-w-full"
        />
      </div>
      {items.length === 0 ? (
        <p className="text-muted-foreground">
          You've watched or dismissed everything from that day's feed.
        </p>
      ) : (
        <ol
          aria-label={heading}
          className="grid grid-cols-1 gap-x-4 gap-y-10 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4"
        >
          {items.map((item) => (
            <FeedCard
              key={item.id}
              item={item}
              now={now}
              actions={actions}
              announce={announce}
              dismissible
            />
          ))}
        </ol>
      )}
    </section>
  );
}
