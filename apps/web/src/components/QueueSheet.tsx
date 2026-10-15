import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpToLine,
  EllipsisVertical,
  ListVideo,
  Play,
  Trash2,
  X,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type RefObject,
} from "react";

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
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetTitle,
  SheetTrigger,
} from "#/components/ui/sheet";
import { formatDuration } from "#/lib/format";
import {
  parseVideoInput,
  queueButtonLabel,
  withItemMoved,
  withoutItem,
} from "#/lib/queue";
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

// The buttons that open the queue (the masthead's, the Library's card) are in
// different components than the sheet, and every page renders its own shell:
// the mounted sheet registers here, and `openQueue()` opens it. Nothing else is
// remembered, so a sheet left open never reopens on the next page.
const queueOpeners = new Set<() => void>();

/** Open the queue sheet of the page you're on. */
export function openQueue() {
  for (const open of queueOpeners) open();
}

/**
 * The watch queue: a masthead button showing how many videos are queued, which
 * opens a sheet from the right to reorder, remove, add by link or clear them.
 * On a watch page the video playing is marked when it's queued. The button is
 * icon-only on narrow screens; its name always includes the count.
 */
export function QueueSheet() {
  const { data: items, isError, refetch } = useQuery(queueQuery);
  const { videoId } = useParams({ strict: false });
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Status | null>(null);
  const statusRef = useRef<HTMLParagraphElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const actions = useQueueActions(setStatus, statusRef);

  useEffect(() => {
    const opener = () => setOpen(true);
    queueOpeners.add(opener);
    return () => {
      queueOpeners.delete(opener);
    };
  }, []);

  const count = items?.length ?? 0;
  const currentIndex = items?.findIndex((item) => item.video_id === videoId);
  const playing = currentIndex !== undefined && currentIndex >= 0;
  const close = () => setOpen(false);

  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setStatus(null);
      }}
    >
      <SheetTrigger
        render={
          <Button
            variant="outline"
            size="lg"
            aria-label={queueButtonLabel(count)}
            className="relative px-0 max-md:size-9 md:gap-2 md:px-3"
          />
        }
      >
        <ListVideo aria-hidden="true" className="size-5 md:size-4" />
        <span aria-hidden="true" className="max-md:hidden">
          Queue
        </span>
        {count > 0 && (
          <span
            aria-hidden="true"
            className="flex h-5 min-w-5 items-center justify-center rounded-full bg-foreground px-1.5 text-xs font-medium text-background tabular-nums max-md:absolute max-md:-top-1 max-md:-right-1 max-md:h-4 max-md:min-w-4 max-md:px-1"
          >
            {count > 99 ? "99+" : count}
          </span>
        )}
      </SheetTrigger>
      <SheetContent
        side="right"
        showCloseButton={false}
        // Not on Clear, which comes first in the tab order.
        initialFocus={closeRef}
        className="gap-0 p-0 data-[side=right]:w-[26rem] data-[side=right]:max-w-full data-[side=right]:sm:max-w-[26rem]"
      >
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b py-3 pr-2 pl-4">
          <div className="flex min-w-0 flex-col">
            <SheetTitle>Queue</SheetTitle>
            <SheetDescription className="text-xs tabular-nums">
              {count === 1 ? "1 video" : `${count} videos`}
              {playing && ` · playing ${currentIndex + 1} of ${count}`}
            </SheetDescription>
          </div>
          <div className="flex items-center gap-1">
            {count > 0 && (
              <ClearQueue
                count={count}
                onCleared={() =>
                  setStatus({ ok: true, message: "Cleared your queue." })
                }
              />
            )}
            <SheetClose
              render={
                <Button
                  ref={closeRef}
                  variant="ghost"
                  size="icon"
                  aria-label="Close queue"
                />
              }
            >
              <X className="size-5" />
            </SheetClose>
          </div>
        </div>
        {/* Focus moves here when a removed item disappears from the list. */}
        <p
          ref={statusRef}
          role="status"
          tabIndex={-1}
          className="shrink-0 px-4 text-xs focus:outline-none empty:hidden has-[span]:py-2"
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
          <p className="p-4">
            Your queue is empty. Add videos from the feed, search or a watch
            page, or paste a link below.
          </p>
        ) : (
          <ol
            aria-label="Queue"
            className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-1"
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
        <div className="mt-auto flex shrink-0 flex-col gap-1 border-t px-4 pt-3 pb-3">
          <AddForm />
          {count > 0 && (
            <p className="text-xs text-muted-foreground">
              Videos leave the queue once you watch them to the end.
            </p>
          )}
        </div>
      </SheetContent>
    </Sheet>
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
          <span className="absolute right-1 bottom-1 rounded bg-black/80 px-1 text-xs leading-4 font-medium text-white tabular-nums">
            {duration}
          </span>
        )}
      </Link>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <Link
          to="/watch/$videoId"
          params={params}
          onClick={onNavigate}
          className="line-clamp-2 min-h-6 text-sm leading-5 font-medium break-words outline-none hover:underline focus-visible:underline"
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
