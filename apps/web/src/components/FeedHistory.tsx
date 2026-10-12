import { useSuspenseQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { formatFeedDate } from "#/lib/format";
import { feedHistoryQuery } from "#/server/feeds";

/** Links to recent feeds, newest first. */
export function FeedHistory() {
  const { data: feeds } = useSuspenseQuery(feedHistoryQuery);

  return (
    <section aria-labelledby="feed-history" className="flex flex-col gap-2">
      <h2 id="feed-history" className="text-lg font-semibold">
        Past feeds
      </h2>
      {feeds.length === 0 ? (
        <p className="text-sm text-gray-600">No feeds yet.</p>
      ) : (
        <ul className="flex flex-col gap-1 text-sm">
          {feeds.map((feed) => (
            <li key={feed.id}>
              <Link
                to="/feed/$date"
                params={{ date: feed.date }}
                className="underline aria-[current=page]:font-medium aria-[current=page]:no-underline"
              >
                {formatFeedDate(feed.date)}
              </Link>{" "}
              <span className="text-gray-600">
                · {feed.item_count} {feed.item_count === 1 ? "video" : "videos"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
