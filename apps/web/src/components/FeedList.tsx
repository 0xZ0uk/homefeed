import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownUp,
  CircleCheck,
  Compass,
  EllipsisVertical,
  EyeOff,
  ListMinus,
  ListPlus,
  Pin,
  type LucideIcon,
} from "lucide-react";
import { useRef, useState, type RefObject } from "react";

import { QueueStatus, useQueueToggle } from "#/components/QueueButton";
import { VideoCard } from "#/components/VideoCard";
import { WhyThisPopover } from "#/components/WhyThisPopover";
import { Button } from "#/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "#/components/ui/dropdown-menu";
import {
  DISMISS_REASONS,
  undismissedItems,
  withItemDismissal,
} from "#/lib/dismiss";
import {
  FEED_SORTS,
  LENGTH_FILTERS,
  isFeedSort,
  matchesLength,
  sortFeedItems,
  type FeedSort,
  type LengthFilter,
} from "#/lib/feed-grid";
import { cn } from "#/lib/utils";
import {
  dismissItem,
  feedQuery,
  loadMoreFeed,
  todayFeedQuery,
  type Feed,
  type FeedItem,
} from "#/server/feeds";

/**
 * A feed as a fixed, ordered grid of video cards, YouTube-style, with chips
 * to narrow it by length and a menu to sort it (ranked, the feed's own order,
 * by default). Every card links to its watch page and has an info button on
 * its thumbnail saying why it's there, with its score breakdown; videos
 * already watched are greyed out. There is deliberately no infinite scroll: today's feed ends in a
 * "Show more" button that appends the next page of picks when pressed.
 *
 * With `dismissible` (today's feed), each card's menu can dismiss it (with an
 * optional reason) and dismissed items are hidden, and "Show more" is offered;
 * otherwise items are shown, marked dismissed, and the feed is fixed.
 */
export function FeedList({
  feed,
  dismissible = false,
}: {
  feed: Feed;
  dismissible?: boolean;
}) {
  // One "now" per render pass keeps every item's age consistent.
  const [now] = useState(() => new Date());
  const [filter, setFilter] = useState<LengthFilter>("all");
  const [sort, setSort] = useState<FeedSort>("ranked");
  const statusRef = useRef<HTMLParagraphElement>(null);
  const { status, dismiss } = useDismiss(feed, statusRef);
  const more = useShowMore(feed);

  if (feed.items.length === 0) {
    return (
      <p className="text-muted-foreground">
        This feed is empty: there were no new videos to pick from. Subscribe to
        more channels on the curation page, then refresh.
      </p>
    );
  }
  const shown = dismissible ? undismissedItems(feed.items) : feed.items;
  const items = sortFeedItems(
    shown.filter((item) => matchesLength(item.duration_seconds, filter)),
    sort,
  );
  return (
    <div className="flex flex-col gap-3">
      <div className="sticky top-14 z-30 -mx-1 flex items-center gap-3 bg-background px-1 py-3">
        <div
          role="group"
          aria-label="Filter by length"
          className="flex min-w-0 flex-1 gap-3 overflow-x-auto"
        >
          {LENGTH_FILTERS.map(({ value, label }) => (
            <Button
              key={value}
              type="button"
              variant="secondary"
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
              className="shrink-0 rounded-lg px-3 aria-pressed:bg-primary aria-pressed:text-primary-foreground"
            >
              {label}
            </Button>
          ))}
        </div>
        <SortMenu sort={sort} onSort={setSort} />
      </div>
      {/* Focus moves here when a dismissed card disappears from the grid. */}
      <p
        ref={statusRef}
        role="status"
        tabIndex={-1}
        className="-mt-2 text-sm focus:outline-none empty:hidden"
      >
        {status && (
          <span
            className={status.ok ? "text-muted-foreground" : "text-destructive"}
          >
            {status.message}
          </span>
        )}
      </p>
      {items.length === 0 ? (
        <p className="py-16 text-center text-muted-foreground">
          {shown.length === 0
            ? "You've dismissed everything in this feed. Refresh it for new picks; dismissed videos won't come back."
            : "Nothing of that length in this feed."}
        </p>
      ) : (
        <ol
          aria-label="Feed"
          className="grid grid-cols-1 gap-x-4 gap-y-10 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4"
        >
          {items.map((item) => (
            <FeedCard
              key={item.id}
              item={item}
              now={now}
              onDismiss={
                dismissible ? (reason) => dismiss(item, reason) : undefined
              }
            />
          ))}
        </ol>
      )}
      {dismissible && <ShowMore more={more} />}
    </div>
  );
}

/**
 * Appending the next page of picks to a stored feed. `exhausted` is set when
 * a press added nothing, and lasts until the feed itself is replaced.
 */
function useShowMore(feed: Feed) {
  const queryClient = useQueryClient();
  const [exhaustedFeedId, setExhaustedFeedId] = useState<number | null>(null);
  const [added, setAdded] = useState(0);

  const mutation = useMutation({
    mutationFn: () => loadMoreFeed({ data: { feedId: feed.id } }),
    onSuccess: (next) => {
      const count = next.items.length - feed.items.length;
      setAdded(count);
      setExhaustedFeedId(count > 0 ? null : feed.id);
      queryClient.setQueryData(todayFeedQuery.queryKey, next);
      queryClient.setQueryData(feedQuery(feed.date).queryKey, next);
    },
  });

  return {
    load: () => mutation.mutate(),
    pending: mutation.isPending,
    failed: mutation.isError,
    exhausted: exhaustedFeedId === feed.id,
    added: mutation.isSuccess ? added : 0,
  };
}

/** The "Show more" button under the grid, with its outcome announced. */
function ShowMore({ more }: { more: ReturnType<typeof useShowMore> }) {
  return (
    <div className="flex flex-col items-center gap-3 pb-6">
      <p
        role="status"
        className={cn(
          "text-sm empty:hidden",
          more.failed ? "text-destructive" : "text-muted-foreground",
        )}
      >
        {more.failed
          ? "Couldn't load more videos. Try again."
          : more.exhausted
            ? "That's everything for today. Refresh the feed for new picks."
            : more.added > 0
              ? `Added ${more.added} more ${more.added === 1 ? "video" : "videos"}.`
              : null}
      </p>
      {!more.exhausted && (
        <Button
          type="button"
          variant="secondary"
          disabled={more.pending}
          onClick={more.load}
          className="rounded-lg px-6"
        >
          {more.pending ? "Loading…" : "Show more"}
        </Button>
      )}
    </div>
  );
}

/** The sort menu at the end of the chips, naming the current sort. */
function SortMenu({
  sort,
  onSort,
}: {
  sort: FeedSort;
  onSort: (sort: FeedSort) => void;
}) {
  const current = FEED_SORTS.find(({ value }) => value === sort);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant="ghost" className="shrink-0 rounded-lg px-3" />}
        aria-label={`Sort: ${current?.label}`}
      >
        <ArrowDownUp aria-hidden="true" />
        <span className="hidden sm:inline">{current?.label}</span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48 py-2">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="px-3">Sort by</DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={sort}
            onValueChange={(value) => {
              if (isFeedSort(value)) onSort(value);
            }}
          >
            {FEED_SORTS.map(({ value, label }) => (
              <DropdownMenuRadioItem
                key={value}
                value={value}
                className="px-3 py-2"
              >
                {label}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
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

/**
 * One feed item as a card: its status icons and an info button (why it's
 * here, with its score) over the thumbnail, and a menu of actions beside the
 * title (see `VideoCard`).
 */
function FeedCard({
  item,
  now,
  onDismiss,
}: {
  item: FeedItem;
  now: Date;
  onDismiss?: (reason: string | null) => void;
}) {
  const queue = useQueueToggle(item.video_id);

  return (
    <VideoCard
      video={item}
      now={now}
      faded={Boolean(item.dismissed_at)}
      top={
        <QueueStatus
          message={queue.message}
          className="mt-1 text-xs empty:hidden"
        />
      }
      overlay={
        <>
          <StatusIcons item={item} />
          <WhyThisPopover
            explanation={item.explanation}
            breakdown={item.breakdown}
          />
        </>
      }
      menu={<CardMenu item={item} queue={queue} onDismiss={onDismiss} />}
    />
  );
}

/**
 * A card's states as small icons in a dark pill at the thumbnail's top-left,
 * each named for screen readers and in a tooltip: pinned, exploring (a
 * channel you don't follow yet), watched, dismissed.
 */
function StatusIcons({ item }: { item: FeedItem }) {
  const statuses: { icon: LucideIcon; label: string }[] = [];
  if (item.is_pinned) statuses.push({ icon: Pin, label: "Pinned" });
  if (item.is_exploration) statuses.push({ icon: Compass, label: "Exploring" });
  if (item.watched) statuses.push({ icon: CircleCheck, label: "Watched" });
  if (item.dismissed_at) {
    statuses.push({
      icon: EyeOff,
      label: item.dismiss_reason
        ? `Dismissed: ${item.dismiss_reason}`
        : "Dismissed",
    });
  }
  if (statuses.length === 0) return null;
  return (
    <ul className="absolute top-1.5 left-1.5 flex items-center gap-1.5 rounded bg-black/70 px-1.5 py-1 text-white">
      {statuses.map(({ icon: Icon, label }) => (
        <li key={label} title={label}>
          <Icon aria-hidden="true" className="size-3.5" />
          <span className="sr-only">{label}</span>
        </li>
      ))}
    </ul>
  );
}

/** A card's "more actions" menu: queue it, and (when allowed) dismiss it. */
function CardMenu({
  item,
  queue,
  onDismiss,
}: {
  item: FeedItem;
  queue: ReturnType<typeof useQueueToggle>;
  onDismiss?: (reason: string | null) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            className="relative z-10 -mt-1 -mr-2 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover/card:opacity-100 [@media(hover:hover)]:focus-visible:opacity-100 [@media(hover:hover)]:data-popup-open:opacity-100"
          />
        }
        aria-label={`More actions for ${item.title}`}
      >
        <EllipsisVertical className="size-5" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56 py-2">
        <DropdownMenuItem
          disabled={!queue.ready}
          onClick={queue.toggle}
          className="px-3 py-2"
        >
          {queue.queued ? <ListMinus /> : <ListPlus />}
          {queue.queued ? "Remove from queue" : "Add to queue"}
        </DropdownMenuItem>
        {onDismiss && (
          <>
            <DropdownMenuSeparator className="my-2" />
            <DropdownMenuGroup>
              <DropdownMenuLabel className="px-3">Dismiss</DropdownMenuLabel>
              {DISMISS_REASONS.map((reason) => (
                <DropdownMenuItem
                  key={reason}
                  onClick={() => onDismiss(reason)}
                  className="px-3 py-2"
                >
                  <EyeOff />
                  {reason}
                </DropdownMenuItem>
              ))}
              <DropdownMenuItem
                onClick={() => onDismiss(null)}
                className="px-3 py-2 pl-9.5 text-muted-foreground"
              >
                No reason
              </DropdownMenuItem>
            </DropdownMenuGroup>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
