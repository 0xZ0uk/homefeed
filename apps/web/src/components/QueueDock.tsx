import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpToLine,
  ChevronDown,
  ChevronUp,
  EllipsisVertical,
  ListVideo,
  Play,
  Trash2,
} from "lucide-react";
import { useRef, useState, type FormEvent, type RefObject } from "react";

import { Button } from "#/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "#/components/ui/dropdown-menu";
import { Input } from "#/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "#/components/ui/popover";
import { formatDuration } from "#/lib/format";
import { parseVideoInput, withItemMoved, withoutItem } from "#/lib/queue";
import { cn } from "#/lib/utils";
import {
  dequeue,
  emptyQueue,
  enqueueVideo,
  moveInQueue,
  queueQuery,
  type QueueItem,
} from "#/server/queue";

type Status = { ok: boolean; message: string };

/**
 * The watch queue, after YouTube's: a bar docked at the bottom right of every
 * signed-in page showing what's up next, which opens the whole queue above it
 * to reorder, remove, add or clear. On a watch page the video playing is
 * marked when it's queued.
 */
export function QueueDock() {
  const { data: items, isError, refetch } = useQuery(queueQuery);
  const { videoId } = useParams({ strict: false });
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Status | null>(null);
  const statusRef = useRef<HTMLParagraphElement>(null);
  const actions = useQueueActions(setStatus, statusRef);

  const count = items?.length ?? 0;
  const currentIndex = items?.findIndex((item) => item.video_id === videoId);
  const playing = currentIndex !== undefined && currentIndex >= 0;
  const headline = items?.[playing ? currentIndex : 0];
  const close = () => setOpen(false);

  return (
    <div className="fixed right-4 bottom-4 z-40 flex justify-end">
      <Popover
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) setStatus(null);
        }}
      >
        <PopoverTrigger
          className={cn(
            "flex items-center gap-3 rounded-xl bg-popover text-left text-popover-foreground shadow-lg ring-1 ring-foreground/10 transition-colors outline-none hover:bg-secondary focus-visible:ring-3 focus-visible:ring-ring/50",
            headline
              ? "w-80 max-w-[calc(100vw-2rem)] py-2.5 pr-3 pl-4"
              : "h-11 px-4",
          )}
        >
          {headline ? (
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="truncate font-medium">
                {itemTitle(headline)}
              </span>
              <span className="text-xs text-muted-foreground">
                Queue •{" "}
                {playing ? (
                  <span className="tabular-nums">
                    {currentIndex + 1} / {count}
                  </span>
                ) : (
                  <>
                    Up next
                    {count > 1 && (
                      <span className="tabular-nums"> · {count} videos</span>
                    )}
                  </>
                )}
              </span>
            </span>
          ) : (
            <>
              <ListVideo aria-hidden="true" className="size-5" />
              <span className="font-medium">Queue</span>
            </>
          )}
          {open ? (
            <ChevronDown aria-hidden="true" className="size-5 shrink-0" />
          ) : (
            <ChevronUp aria-hidden="true" className="size-5 shrink-0" />
          )}
        </PopoverTrigger>
        <PopoverContent
          side="top"
          align="end"
          sideOffset={8}
          className="w-[26rem] max-w-[calc(100vw-2rem)] gap-0 overflow-hidden rounded-xl p-0 shadow-lg"
        >
          <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
            <PopoverHeader className="min-w-0">
              <PopoverTitle className="text-base">Queue</PopoverTitle>
              <p className="text-xs text-muted-foreground tabular-nums">
                {count === 1 ? "1 video" : `${count} videos`}
                {playing && ` · playing ${currentIndex + 1} of ${count}`}
              </p>
            </PopoverHeader>
            {count > 0 && (
              <ClearQueue
                count={count}
                onCleared={() =>
                  setStatus({ ok: true, message: "Cleared your queue." })
                }
              />
            )}
          </div>
          {/* Focus moves here when a removed item disappears from the list. */}
          <p
            ref={statusRef}
            role="status"
            tabIndex={-1}
            className="px-4 text-xs focus:outline-none empty:hidden has-[span]:py-2"
          >
            {status && (
              <span
                className={
                  status.ok ? "text-muted-foreground" : "text-destructive"
                }
              >
                {status.message}
              </span>
            )}
          </p>
          {isError ? (
            <div role="alert" className="flex flex-col items-start gap-2 p-4">
              <p>Couldn't load your queue. The API may be down.</p>
              <button
                type="button"
                onClick={() => void refetch()}
                className="underline"
              >
                Try again
              </button>
            </div>
          ) : !items ? (
            <p className="p-4 text-muted-foreground">Loading your queue…</p>
          ) : items.length === 0 ? (
            <PopoverDescription className="p-4">
              Your queue is empty. Add videos from the feed, search or a watch
              page, or paste a link below.
            </PopoverDescription>
          ) : (
            <ol
              aria-label="Queue"
              className="max-h-[min(28rem,55svh)] overflow-y-auto overscroll-contain py-1"
            >
              {items.map((item, index) => (
                <QueueRow
                  key={item.id}
                  item={item}
                  index={index}
                  count={items.length}
                  current={item.video_id === videoId}
                  actions={actions}
                  onNavigate={close}
                />
              ))}
            </ol>
          )}
          <div className="flex flex-col gap-1 border-t px-4 pt-3 pb-2">
            <AddForm />
            {count > 0 && (
              <PopoverDescription className="text-xs">
                Videos leave the queue once you watch them to the end.
              </PopoverDescription>
            )}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}

interface QueueActions {
  move: (item: QueueItem, position: number) => void;
  remove: (item: QueueItem) => void;
}

const QUEUE_MUTATION = ["queue", "edit"];

/**
 * Moving and removing apply to the cached queue at once; the API calls run one
 * at a time, and the queue is refetched once the last one settles (undoing any
 * that failed). Both outcomes are announced.
 */
function useQueueActions(
  setStatus: (status: Status) => void,
  statusRef: RefObject<HTMLParagraphElement | null>,
): QueueActions {
  const queryClient = useQueryClient();
  const update = (change: (items: QueueItem[]) => QueueItem[]) =>
    queryClient.setQueryData(queueQuery.queryKey, (old) =>
      old ? change(old) : old,
    );
  const refetch = () => {
    // Only after the last pending edit, so a refetch can't undo later ones.
    if (queryClient.isMutating({ mutationKey: QUEUE_MUTATION }) <= 1) {
      return queryClient.invalidateQueries({ queryKey: queueQuery.queryKey });
    }
  };
  const shared = { mutationKey: QUEUE_MUTATION, scope: { id: "queue" } };

  const move = useMutation({
    ...shared,
    mutationFn: ({ item, position }: { item: QueueItem; position: number }) =>
      moveInQueue({ data: { id: item.id, position } }),
    onMutate: async ({ item, position }) => {
      await queryClient.cancelQueries({ queryKey: queueQuery.queryKey });
      update((items) => withItemMoved(items, item.id, position));
      setStatus({
        ok: true,
        message: `Moved “${itemTitle(item)}” to position ${position + 1}.`,
      });
    },
    onError: (_error, { item }) => {
      setStatus({
        ok: false,
        message: `Couldn't move “${itemTitle(item)}”. Try again.`,
      });
    },
    onSettled: refetch,
  });

  const remove = useMutation({
    ...shared,
    mutationFn: (item: QueueItem) => dequeue({ data: { id: item.id } }),
    onMutate: async (item) => {
      await queryClient.cancelQueries({ queryKey: queueQuery.queryKey });
      update((items) => withoutItem(items, item.id));
      setStatus({ ok: true, message: `Removed “${itemTitle(item)}”.` });
      // After the menu has closed and handed focus back to its trigger.
      requestAnimationFrame(() => statusRef.current?.focus());
    },
    onError: (_error, item) => {
      setStatus({
        ok: false,
        message: `Couldn't remove “${itemTitle(item)}”. Try again.`,
      });
    },
    onSettled: refetch,
  });

  return {
    move: (item, position) => move.mutate({ item, position }),
    remove: (item) => remove.mutate(item),
  };
}

function itemTitle(item: QueueItem): string {
  return item.title ?? item.video_id;
}

/** One queued video: thumbnail with its length, title and channel, and a
 * menu to reorder or remove it. The video playing is marked. */
function QueueRow({
  item,
  index,
  count,
  current,
  actions,
  onNavigate,
}: {
  item: QueueItem;
  index: number;
  count: number;
  current: boolean;
  actions: QueueActions;
  onNavigate: () => void;
}) {
  const title = itemTitle(item);
  const duration = formatDuration(item.duration_seconds);
  const params = { videoId: item.video_id };
  const isFirst = index === 0;
  const isLast = index === count - 1;
  const rowRef = useRef<HTMLLIElement>(null);

  // React moves the row's element to reorder it, which drops focus; put it
  // back on the row's menu button.
  function moveTo(position: number) {
    actions.move(item, position);
    requestAnimationFrame(() =>
      rowRef.current?.querySelector<HTMLElement>("[data-row-menu]")?.focus(),
    );
  }

  return (
    <li
      ref={rowRef}
      aria-current={current ? "true" : undefined}
      className={cn(
        "group/row flex items-center gap-2 py-1.5 pr-1 pl-1.5 hover:bg-secondary/60",
        current && "bg-secondary hover:bg-secondary",
      )}
    >
      <span
        aria-hidden="true"
        className="flex w-5 shrink-0 justify-center text-xs text-muted-foreground tabular-nums"
      >
        {current ? <Play className="size-3 fill-current" /> : index + 1}
      </span>
      {/* Mouse-only; the title link is the one in the tab order. */}
      <Link
        to="/watch/$videoId"
        params={params}
        onClick={onNavigate}
        tabIndex={-1}
        aria-hidden="true"
        className="relative aspect-video w-24 shrink-0 overflow-hidden rounded-lg bg-secondary"
      >
        {item.thumbnail_url && (
          <img
            src={item.thumbnail_url}
            alt=""
            loading="lazy"
            className="size-full rounded-[inherit] object-cover outline outline-1 -outline-offset-1 outline-black/10 dark:outline-white/10"
          />
        )}
        {duration && (
          <span className="absolute right-1 bottom-1 rounded bg-black/80 px-1 text-[0.6875rem] leading-4 font-medium text-white tabular-nums">
            {duration}
          </span>
        )}
      </Link>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <Link
          to="/watch/$videoId"
          params={params}
          onClick={onNavigate}
          className="line-clamp-2 text-sm leading-5 font-medium break-words outline-none hover:underline focus-visible:underline"
        >
          {current && <span className="sr-only">Playing: </span>}
          {title}
        </Link>
        {item.channel_title && (
          <span className="truncate text-xs text-muted-foreground">
            {item.channel_title}
          </span>
        )}
      </div>
      <DropdownMenu>
        <DropdownMenuTrigger
          data-row-menu=""
          render={
            <Button
              variant="ghost"
              size="icon"
              className="shrink-0 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover/row:opacity-100 [@media(hover:hover)]:focus-visible:opacity-100 [@media(hover:hover)]:data-popup-open:opacity-100"
            />
          }
          aria-label={`More actions for ${title}`}
        >
          <EllipsisVertical className="size-5" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52 py-2">
          <DropdownMenuItem
            disabled={isFirst}
            onClick={() => moveTo(0)}
            className="px-3 py-2"
          >
            <ArrowUpToLine />
            Move to top
          </DropdownMenuItem>
          <DropdownMenuItem
            disabled={isFirst}
            onClick={() => moveTo(index - 1)}
            className="px-3 py-2"
          >
            <ArrowUp />
            Move up
          </DropdownMenuItem>
          <DropdownMenuItem
            disabled={isLast}
            onClick={() => moveTo(index + 1)}
            className="px-3 py-2"
          >
            <ArrowDown />
            Move down
          </DropdownMenuItem>
          <DropdownMenuSeparator className="my-2" />
          <DropdownMenuItem
            variant="destructive"
            onClick={() => actions.remove(item)}
            className="px-3 py-2"
          >
            <Trash2 />
            Remove from queue
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  );
}

function AddForm() {
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: (videoId: string) => enqueueVideo({ data: { videoId } }),
    onSuccess: async (result) => {
      if (result.ok) setInput("");
      await queryClient.invalidateQueries({ queryKey: queueQuery.queryKey });
    },
  });
  const result = mutation.data;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const videoId = parseVideoInput(input);
    if (!videoId) {
      setError("Paste a YouTube video link or an 11-character video id.");
      return;
    }
    setError(null);
    mutation.mutate(videoId);
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-1">
      <div className="flex gap-2">
        <Input
          type="text"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Paste a YouTube link to add it"
          aria-label="Add a video by link or id"
          required
          aria-invalid={error !== null || result?.ok === false}
          aria-describedby="queue-video-status"
          className="h-8 min-w-0 flex-1"
        />
        <Button
          type="submit"
          variant="secondary"
          disabled={mutation.isPending}
          className="px-3"
        >
          {mutation.isPending ? "Adding…" : "Add"}
        </Button>
      </div>
      <p
        id="queue-video-status"
        role="status"
        className="text-xs empty:hidden has-[span]:min-h-4"
      >
        {error && <span className="text-destructive">{error}</span>}
        {!error && mutation.isError && (
          <span className="text-destructive">
            Couldn't queue that. Try again later.
          </span>
        )}
        {!error && result?.ok === false && (
          <span className="text-destructive">{result.message}</span>
        )}
        {!error && result?.ok === true && (
          <span className="text-muted-foreground">
            {result.created
              ? `Added “${itemTitle(result.item)}”.`
              : `“${itemTitle(result.item)}” is already in your queue.`}
          </span>
        )}
      </p>
    </form>
  );
}

function ClearQueue({
  count,
  onCleared,
}: {
  count: number;
  onCleared: () => void;
}) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const mutation = useMutation({
    mutationFn: () => emptyQueue(),
    onSuccess: () => {
      setConfirming(false);
      onCleared();
    },
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: queueQuery.queryKey }),
  });

  if (!confirming) {
    return (
      <Button variant="ghost" size="sm" onClick={() => setConfirming(true)}>
        Clear
      </Button>
    );
  }
  return (
    <div
      role="group"
      aria-label={`Remove all ${count} ${count === 1 ? "video" : "videos"} from your queue?`}
      className="flex shrink-0 items-center gap-1"
    >
      <Button
        variant="destructive"
        size="sm"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {mutation.isPending
          ? "Clearing…"
          : mutation.isError
            ? "Retry clear"
            : "Clear all"}
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
        Keep
      </Button>
    </div>
  );
}
