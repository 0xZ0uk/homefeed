import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
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
import { WhyThisPopover } from "#/components/WhyThisPopover";
import { Avatar, AvatarFallback, AvatarImage } from "#/components/ui/avatar";
import { Button } from "#/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "#/components/ui/dropdown-menu";
import {
  DISMISS_REASONS,
  undismissedItems,
  withItemDismissal,
} from "#/lib/dismiss";
import {
  LENGTH_FILTERS,
  channelColor,
  matchesLength,
  type LengthFilter,
} from "#/lib/feed-grid";
import { formatAge, formatDuration, formatViews } from "#/lib/format";
import { cn } from "#/lib/utils";
import {
  dismissItem,
  feedQuery,
  todayFeedQuery,
  type Feed,
  type FeedItem,
} from "#/server/feeds";

/**
 * A feed as a fixed, ordered grid of video cards, YouTube-style, with chips
 * to narrow it by length. Every card links to its watch page and says why
 * it's there, expandable into its score breakdown. There is deliberately no
 * pagination or "load more": the feed is the whole grid.
 *
 * With `dismissible`, each card's menu can dismiss it (with an optional
 * reason) and dismissed items are hidden; otherwise they're shown, marked
 * dismissed.
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
  const statusRef = useRef<HTMLParagraphElement>(null);
  const { status, dismiss } = useDismiss(feed, statusRef);

  if (feed.items.length === 0) {
    return (
      <p className="text-muted-foreground">
        This feed is empty: there were no new videos to pick from. Subscribe to
        more channels on the curation page, then refresh.
      </p>
    );
  }
  const shown = dismissible ? undismissedItems(feed.items) : feed.items;
  const items = shown.filter((item) =>
    matchesLength(item.duration_seconds, filter),
  );
  return (
    <div className="flex flex-col gap-3">
      <div
        role="group"
        aria-label="Filter by length"
        className="sticky top-14 z-30 -mx-1 flex gap-3 overflow-x-auto bg-background px-1 py-3"
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
            <VideoCard
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

/**
 * One video: its status icons and why it's here, its thumbnail (or, when it
 * has none, a placeholder in the channel's colour), then the channel's avatar
 * beside title, channel and stats, and a menu of actions. The title is the
 * card's one link, stretched over the whole card; the controls sit above it.
 */
function VideoCard({
  item,
  now,
  onDismiss,
}: {
  item: FeedItem;
  now: Date;
  onDismiss?: (reason: string | null) => void;
}) {
  const queue = useQueueToggle(item.video_id);
  const duration = formatDuration(item.duration_seconds);
  const age = formatAge(item.published_at, now);
  const views = formatViews(item.view_count);
  const thumbnail = item.thumbnail_url;
  const color = channelColor(item.channel_id);

  return (
    <li
      className={cn(
        "group/card relative flex flex-col gap-3",
        item.dismissed_at && "opacity-60",
      )}
    >
      <QueueStatus
        message={queue.message}
        className="mt-1 text-xs empty:hidden"
      />
      <div className="relative z-10 -mb-1 flex items-center gap-2 text-xs text-muted-foreground">
        <StatusIcons item={item} />
        <WhyThisPopover
          explanation={item.explanation}
          breakdown={item.breakdown}
        />
      </div>
      <div
        className="relative aspect-video overflow-hidden rounded-xl bg-secondary transition-[border-radius] group-hover/card:rounded-none"
        style={thumbnail ? undefined : { backgroundColor: color }}
      >
        {thumbnail ? (
          <img
            src={thumbnail}
            alt=""
            loading="lazy"
            className="size-full rounded-[inherit] object-cover outline outline-1 -outline-offset-1 outline-black/10 dark:outline-white/10"
          />
        ) : (
          <span
            aria-hidden="true"
            className="flex size-full items-center justify-center bg-linear-to-br from-white/10 to-black/30 text-7xl font-bold text-white/25"
          >
            {initial(item.channel_title)}
          </span>
        )}
        {duration && (
          <span className="absolute right-1.5 bottom-1.5 rounded bg-black/80 px-1 py-px text-xs font-medium text-white tabular-nums">
            {duration}
          </span>
        )}
      </div>
      <div className="flex gap-3">
        <Avatar aria-hidden="true" className="size-9">
          {item.channel_thumbnail_url && (
            <AvatarImage
              src={avatarUrl(item.channel_thumbnail_url)}
              alt=""
              loading="lazy"
              referrerPolicy="no-referrer"
            />
          )}
          <AvatarFallback
            className="font-medium text-white"
            style={{ backgroundColor: color }}
          >
            {initial(item.channel_title)}
          </AvatarFallback>
        </Avatar>
        <div className="flex min-w-0 flex-1 flex-col">
          <h3 className="line-clamp-2 leading-snug font-medium">
            <Link
              to="/watch/$videoId"
              params={{ videoId: item.video_id }}
              className="outline-none before:absolute before:-inset-2 before:rounded-2xl focus-visible:before:ring-3 focus-visible:before:ring-ring/50"
            >
              {item.title}
            </Link>
          </h3>
          <p className="mt-1 truncate text-sm text-muted-foreground">
            {item.channel_title}
          </p>
          <p className="flex flex-wrap gap-x-1 text-sm text-muted-foreground">
            {[
              views,
              age && item.published_at && (
                <time dateTime={item.published_at} suppressHydrationWarning>
                  {age}
                </time>
              ),
            ]
              .filter(Boolean)
              .map((part, index) => (
                <span key={index} className="tabular-nums">
                  {index > 0 && "• "}
                  {part}
                </span>
              ))}
          </p>
        </div>
        <CardMenu item={item} queue={queue} onDismiss={onDismiss} />
      </div>
    </li>
  );
}

/**
 * A card's states as small icons, each named for screen readers and in a
 * tooltip: pinned, exploring (a channel you don't follow yet), dismissed.
 */
function StatusIcons({ item }: { item: FeedItem }) {
  const statuses: { icon: LucideIcon; label: string }[] = [];
  if (item.is_pinned) statuses.push({ icon: Pin, label: "Pinned" });
  if (item.is_exploration) statuses.push({ icon: Compass, label: "Exploring" });
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
    <ul className="flex h-4 shrink-0 items-center gap-1.5">
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

/**
 * YouTube channel avatars come at full size (`=s0`); ask for one sized for
 * the card instead (2x its 36px).
 */
function avatarUrl(url: string): string {
  return url.replace(/=s\d+[^/]*$/, "=s72");
}

function initial(name: string): string {
  return name.trim().charAt(0).toUpperCase();
}
