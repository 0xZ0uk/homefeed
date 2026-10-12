import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { WhyThisPopover } from "#/components/WhyThisPopover";
import { showsThumbnails, type DisplayPrefs } from "#/lib/display";
import { formatAge, formatDuration, formatViews } from "#/lib/format";
import type { Feed, FeedItem } from "#/server/feeds";

/**
 * A feed as a fixed, numbered list. Every item links to its watch page and
 * says why it's there, expandable into its score breakdown. There is
 * deliberately no pagination or "load more": the feed is the whole list.
 */
export function FeedList({
  feed,
  display,
}: {
  feed: Feed;
  display: DisplayPrefs;
}) {
  // One "now" per render pass keeps every item's age consistent.
  const [now] = useState(() => new Date());

  if (feed.items.length === 0) {
    return (
      <p className="text-gray-600">
        This feed is empty: there were no new videos to pick from. Subscribe to
        more channels on the curation page, then refresh.
      </p>
    );
  }
  return (
    <ol className="flex flex-col divide-y" aria-label="Feed">
      {feed.items.map((item) => (
        <FeedItemRow key={item.id} item={item} display={display} now={now} />
      ))}
    </ol>
  );
}

function FeedItemRow({
  item,
  display,
  now,
}: {
  item: FeedItem;
  display: DisplayPrefs;
  now: Date;
}) {
  const duration = formatDuration(item.duration_seconds);
  const age = formatAge(item.published_at, now);
  const views = display.viewCounts ? formatViews(item.view_count) : null;
  const thumbnails = showsThumbnails(display);
  const params = { videoId: item.video_id };

  // Only the title is a link: the explanation is a button of its own.
  return (
    <li className="flex gap-4 py-3">
      {thumbnails && (
        // A second, mouse-only way in: the title link is the one in the
        // tab order and the accessibility tree.
        <Link
          to="/watch/$videoId"
          params={params}
          tabIndex={-1}
          aria-hidden="true"
          className="relative aspect-video w-40 shrink-0 overflow-hidden rounded bg-gray-200"
        >
          {item.thumbnail_url && (
            <img
              src={item.thumbnail_url}
              alt=""
              loading="lazy"
              className="size-full object-cover"
            />
          )}
          {duration && (
            <span className="absolute right-1 bottom-1 rounded bg-black/80 px-1 text-xs text-white tabular-nums">
              {duration}
            </span>
          )}
        </Link>
      )}
      <div className="flex min-w-0 flex-col gap-1">
        <h3 className="font-medium">
          <Link
            to="/watch/$videoId"
            params={params}
            className="hover:underline"
          >
            {item.title}
          </Link>
        </h3>
        <p className="flex flex-wrap gap-x-2 text-sm text-gray-600">
          <span>{item.channel_title}</span>
          {duration && !thumbnails && (
            <span className="tabular-nums">· {duration}</span>
          )}
          {age && item.published_at && (
            <span>
              ·{" "}
              <time dateTime={item.published_at} suppressHydrationWarning>
                {age}
              </time>
            </span>
          )}
          {views && <span>· {views}</span>}
        </p>
        <div className="flex flex-wrap items-center gap-2 text-sm text-gray-500">
          {item.is_pinned && <Badge>Pinned</Badge>}
          {item.is_exploration && <Badge>Exploring</Badge>}
          <WhyThisPopover
            explanation={item.explanation}
            breakdown={item.breakdown}
          />
        </div>
      </div>
    </li>
  );
}

function Badge({ children }: { children: string }) {
  return (
    <span className="rounded border px-1.5 text-xs font-medium text-gray-700">
      {children}
    </span>
  );
}
