import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDownUp } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { ActionStatusLine, useActionStatus } from "#/components/ActionStatus";
import { FeedCard } from "#/components/FeedCard";
import { FeedEnd } from "#/components/FeedEnd";
import { useFeedActions } from "#/components/use-feed-actions";
import { Button } from "#/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "#/components/ui/dropdown-menu";
import { undismissedItems } from "#/lib/dismiss";
import {
  FEED_FILTERS,
  FEED_SORTS,
  isFeedSort,
  matchesFilter,
  sortFeedItems,
  type FeedFilter,
  type FeedSort,
} from "#/lib/feed-grid";
import {
  LANES,
  emptyReason,
  laneEmptyMessage,
  splitLanes,
} from "#/lib/feed-lanes";
import { cn } from "#/lib/utils";
import { discoveryVideosQuery } from "#/server/discover";
import {
  feedQuery,
  loadMoreFeed,
  todayFeedQuery,
  type Feed,
} from "#/server/feeds";

/**
 * A feed as a fixed, ordered grid of video cards in two lanes, "New to you"
 * (from channels I don't follow) and "From your channels", with chips to narrow
 * it by what I'm in the mood for (new to me, quick, medium, deep dives) and a
 * menu to sort it (ranked, the feed's own order, by default). The chips and
 * the sort apply to both lanes, and a lane with nothing to show says why.
 * Every card links to its watch page, says why it's there (with its score
 * breakdown under "Details"), and has quick actions that steer the feed:
 * "More like this", "Less like this" and "Later"; a watched card can be rated
 * on the spot. What an action did is said in a status line hanging under the
 * chips, with an Undo. There is deliberately no infinite scroll: today's feed
 * ends in a "Show more" button that appends the next page of picks when
 * pressed, and once that has nothing more, in a closing block (see `FeedEnd`).
 *
 * With `dismissible` (today's feed), each card's menu can dismiss it (with an
 * optional reason, under "Not for me"; the status line offers to restore it)
 * and dismissed items are hidden, and "Show more" is offered; otherwise items
 * are shown, marked dismissed, and the feed is fixed. A `shelf` is shown at
 * the top of the "New to you" lane, e.g. the Discovery carousel, which is a
 * shelf of picks of its own: the chips and the sort don't touch it.
 */
export function FeedList({
  feed,
  dismissible = false,
  shelf,
}: {
  feed: Feed;
  dismissible?: boolean;
  shelf?: ReactNode;
}) {
  // One "now" per render pass keeps every item's age consistent.
  const [now] = useState(() => new Date());
  const [filter, setFilter] = useState<FeedFilter>("all");
  const [sort, setSort] = useState<FeedSort>("ranked");
  const { status, announce, ref: statusRef } = useActionStatus();
  const actions = useFeedActions(feed, announce);
  const more = useShowMore(feed);

  if (feed.items.length === 0) {
    return (
      <p className="text-muted-foreground">
        This feed is empty: there were no new videos to pick from. Subscribe to
        more channels on the Subscriptions page, then refresh.
      </p>
    );
  }
  const kept = dismissible ? undismissedItems(feed.items) : feed.items;
  // Each lane as the feed has it, without its dismissed videos and as shown.
  const inFeed = splitLanes(feed.items);
  const undismissed = splitLanes(kept);
  const shown = splitLanes(
    sortFeedItems(
      kept.filter((item) => matchesFilter(item, filter)),
      sort,
    ),
  );
  const filterLabel =
    FEED_FILTERS.find(({ value }) => value === filter)?.label ?? "";

  return (
    <div className="flex flex-col gap-3">
      <div
        data-sticky-chips
        className="sticky top-14 z-30 -mx-1 flex items-center gap-3 bg-background px-1 py-3"
      >
        <div
          role="group"
          aria-label="Filter by intent"
          className="flex min-w-0 flex-1 gap-3 overflow-x-auto"
        >
          {FEED_FILTERS.map(({ value, label }) => (
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
        {/* Hangs under the bar, so it's in view wherever the page is scrolled to.
            Focus moves here when a card's control is gone, e.g. a dismissed card. */}
        <ActionStatusLine
          status={status}
          statusRef={statusRef}
          className="absolute top-full left-1 mt-1 max-w-[calc(100%-0.5rem)]"
        />
      </div>
      {LANES.map(({ id, title }) => {
        const reason = emptyReason(
          inFeed[id].length,
          undismissed[id].length,
          shown[id].length,
        );
        return (
          <Lane
            key={id}
            title={title}
            count={shown[id].length}
            shelf={id === "fresh" ? shelf : undefined}
            empty={reason && laneEmptyMessage(id, reason, filterLabel)}
          >
            {shown[id].map((item) => (
              <FeedCard
                key={item.id}
                item={item}
                now={now}
                actions={actions}
                announce={announce}
                dismissible={dismissible}
              />
            ))}
          </Lane>
        );
      })}
      {dismissible && <ShowMore more={more} />}
      {dismissible && more.exhausted && (
        <FeedEnd now={now} announce={announce} />
      )}
    </div>
  );
}

/**
 * One lane of the feed: its heading with how many videos it shows, an optional
 * `shelf` of extra picks, and the videos as an ordered grid, or `empty` (what
 * to say when there are none).
 */
function Lane({
  title,
  count,
  shelf,
  empty,
  children,
}: {
  title: string;
  count: number;
  shelf?: ReactNode;
  empty: string | null;
  children: ReactNode;
}) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 pt-2">
      <h2 id={headingId} className="text-xl font-bold">
        {title}
        {/* Inline, not flex items: a screen reader reads "New to you, 12
            videos" without a gap before the comma. */}
        <span
          aria-hidden="true"
          className="ml-2.5 text-base font-normal text-muted-foreground tabular-nums"
        >
          {count}
        </span>
        <span className="sr-only">
          , {count} {count === 1 ? "video" : "videos"}
        </span>
      </h2>
      {shelf}
      {empty ? (
        <p className="py-6 text-muted-foreground">{empty}</p>
      ) : (
        <ol
          aria-label={title}
          className="grid grid-cols-1 gap-x-4 gap-y-10 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4"
        >
          {children}
        </ol>
      )}
    </section>
  );
}

/**
 * Appending the next page of picks to a stored feed. `exhausted` is set when
 * a press added nothing, and lasts until the feed itself is replaced. What
 * Discovery shows leaves out what the feed holds, so it's loaded again once
 * the feed has grown.
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
      if (count > 0) {
        void queryClient.invalidateQueries({
          queryKey: discoveryVideosQuery.queryKey,
        });
      }
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

/**
 * The "Show more" button under the lanes, with its outcome announced. Once
 * there is nothing more the button goes and the closing block takes over; the
 * status line then only says so for those who can't see it.
 */
function ShowMore({ more }: { more: ReturnType<typeof useShowMore> }) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-3",
        !more.exhausted && "pb-6",
      )}
    >
      <p
        role="status"
        className={cn(
          "text-sm empty:sr-only",
          more.exhausted && "sr-only",
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
