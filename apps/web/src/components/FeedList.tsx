import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useRef, useState, type RefObject } from "react";

import { DismissMenu } from "#/components/DismissMenu";
import { WhyThisPopover } from "#/components/WhyThisPopover";
import { undismissedItems, withItemDismissal } from "#/lib/dismiss";
import { showsThumbnails, type DisplayPrefs } from "#/lib/display";
import { formatAge, formatDuration, formatViews } from "#/lib/format";
import {
  dismissItem,
  feedQuery,
  todayFeedQuery,
  type Feed,
  type FeedItem,
} from "#/server/feeds";

/**
 * A feed as a fixed, numbered list. Every item links to its watch page and
 * says why it's there, expandable into its score breakdown. There is
 * deliberately no pagination or "load more": the feed is the whole list.
 *
 * With `dismissible`, each item can be dismissed (with an optional reason) and
 * dismissed items are hidden; otherwise they're shown, marked dismissed.
 */
export function FeedList({
  feed,
  display,
  dismissible = false,
}: {
  feed: Feed;
  display: DisplayPrefs;
  dismissible?: boolean;
}) {
  // One "now" per render pass keeps every item's age consistent.
  const [now] = useState(() => new Date());
  const statusRef = useRef<HTMLParagraphElement>(null);
  const { status, dismiss } = useDismiss(feed, statusRef);

  if (feed.items.length === 0) {
    return (
      <p className="text-gray-600">
        This feed is empty: there were no new videos to pick from. Subscribe to
        more channels on the curation page, then refresh.
      </p>
    );
  }
  const items = dismissible ? undismissedItems(feed.items) : feed.items;
  return (
    <div className="flex flex-col gap-2">
      {/* Focus moves here when a dismissed item disappears from the list. */}
      <p
        ref={statusRef}
        role="status"
        tabIndex={-1}
        className="text-sm focus:outline-none"
      >
        {status && (
          <span className={status.ok ? "text-gray-600" : "text-red-600"}>
            {status.message}
          </span>
        )}
      </p>
      {items.length === 0 ? (
        <p className="text-gray-600">
          You've dismissed everything in this feed. Refresh it for new picks;
          dismissed videos won't come back.
        </p>
      ) : (
        <ol className="flex flex-col divide-y" aria-label="Feed">
          {items.map((item) => (
            <FeedItemRow
              key={item.id}
              item={item}
              display={display}
              now={now}
              onDismiss={
                dismissible ? (reason) => dismiss(item, reason) : undefined
              }
            />
          ))}
        </ol>
      )}
    </div>
  );
}

type DismissStatus = { ok: boolean; message: string };

/**
 * Dismissing an item: it's hidden at once and restored if the API call fails.
 * Both outcomes are announced in a status message that takes focus, since the
 * item (and the focused menu in it) is gone.
 */
function useDismiss(
  feed: Feed,
  statusRef: RefObject<HTMLParagraphElement | null>,
) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<DismissStatus | null>(null);

  function update(
    itemId: number,
    dismissal: Pick<FeedItem, "dismissed_at" | "dismiss_reason">,
  ) {
    const apply = (old: Feed | null | undefined) =>
      old ? withItemDismissal(old, itemId, dismissal) : old;
    queryClient.setQueryData(todayFeedQuery.queryKey, apply);
    queryClient.setQueryData(feedQuery(feed.date).queryKey, apply);
  }

  function announce(next: DismissStatus) {
    setStatus(next);
    statusRef.current?.focus();
  }

  const mutation = useMutation({
    mutationFn: ({ item, reason }: { item: FeedItem; reason: string | null }) =>
      dismissItem({ data: { id: item.id, reason } }),
    onMutate: ({ item, reason }) => {
      update(item.id, {
        dismissed_at: new Date().toISOString(),
        dismiss_reason: reason,
      });
      announce({ ok: true, message: `Dismissed “${item.title}”.` });
    },
    onSuccess: (saved) => update(saved.id, saved),
    onError: (_error, { item }) => {
      update(item.id, item);
      announce({
        ok: false,
        message: `Couldn't dismiss “${item.title}”. Try again later.`,
      });
    },
  });

  const dismiss = (item: FeedItem, reason: string | null) =>
    mutation.mutate({ item, reason });
  return { status, dismiss };
}

function FeedItemRow({
  item,
  display,
  now,
  onDismiss,
}: {
  item: FeedItem;
  display: DisplayPrefs;
  now: Date;
  onDismiss?: (reason: string | null) => void;
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
      <div className="flex min-w-0 flex-1 flex-col gap-1">
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
          {item.dismissed_at && (
            <Badge>
              {item.dismiss_reason
                ? `Dismissed: ${item.dismiss_reason}`
                : "Dismissed"}
            </Badge>
          )}
          <WhyThisPopover
            explanation={item.explanation}
            breakdown={item.breakdown}
          />
        </div>
      </div>
      {onDismiss && <DismissMenu title={item.title} onDismiss={onDismiss} />}
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
