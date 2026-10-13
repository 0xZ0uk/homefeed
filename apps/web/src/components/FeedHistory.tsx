import { useSuspenseQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { formatFeedDate } from "#/lib/format";
import { feedHistoryQuery } from "#/server/feeds";

/** Links to recent feeds, newest first. */
export function FeedHistory() {
  const { data: feeds } = useSuspenseQuery(feedHistoryQuery);

  return (
    <section aria-labelledby="feed-history" className="flex flex-col gap-2">
      <h2 id="feed-history" className="text-sm font-medium">
        Past feeds
      </h2>
      {feeds.length === 0 ? (
        <p className="text-sm text-muted-foreground">No feeds yet.</p>
      ) : (
        <ul className="flex flex-wrap gap-2 text-sm">
          {feeds.map((feed) => (
            <li key={feed.id}>
              <Link
                to="/feed/$date"
                params={{ date: feed.date }}
                className="group flex h-8 items-center gap-1.5 rounded-lg bg-secondary px-3 font-medium outline-none hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/50 aria-[current=page]:bg-primary aria-[current=page]:text-primary-foreground"
              >
                {formatFeedDate(feed.date)}
                <span className="font-normal text-muted-foreground group-aria-[current=page]:text-primary-foreground/70">
                  · {feed.item_count}{" "}
                  {feed.item_count === 1 ? "video" : "videos"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
