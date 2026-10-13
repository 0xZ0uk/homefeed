import {
  useMutation,
  useQueryClient,
  useQueryErrorResetBoundary,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { Link, createFileRoute, useRouter } from "@tanstack/react-router";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type RefObject,
} from "react";

import { Button, buttonVariants } from "#/components/ui/button";
import { cn } from "#/lib/utils";
import { AppShell } from "#/components/AppShell";
import { formatDuration } from "#/lib/format";
import { parseVideoInput, withItemMoved, withoutItem } from "#/lib/queue";
import {
  dequeue,
  emptyQueue,
  enqueueVideo,
  moveInQueue,
  queueQuery,
  type QueueItem,
} from "#/server/queue";

/** The watch queue: videos to watch next, in an order the user sets. */
export const Route = createFileRoute("/queue")({
  head: () => ({ meta: [{ title: "Queue · Homefeed" }] }),
  loader: ({ context: { queryClient } }) =>
    Promise.all([queryClient.ensureQueryData(queueQuery)]),
  component: Queue,
  errorComponent: QueueError,
});

type Status = { ok: boolean; message: string };

function Queue() {
  const { data: items } = useSuspenseQuery(queueQuery);
  const [status, setStatus] = useState<Status | null>(null);
  const statusRef = useRef<HTMLParagraphElement>(null);
  const actions = useQueueActions(setStatus, statusRef);
  const first = items[0];

  return (
    <AppShell className="flex max-w-4xl flex-col gap-6">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <h2 className="text-xl font-semibold">
          Queue
          {items.length > 0 && (
            <span className="font-normal text-muted-foreground">
              {" "}
              · {items.length} {items.length === 1 ? "video" : "videos"}
            </span>
          )}
        </h2>
        {first && (
          <Link
            to="/watch/$videoId"
            params={{ videoId: first.video_id }}
            className={cn(buttonVariants({ size: "lg" }), "px-4")}
          >
            Watch next
          </Link>
        )}
      </div>
      <AddForm />
      {/* Focus moves here when a removed item disappears from the list. */}
      <p
        ref={statusRef}
        role="status"
        tabIndex={-1}
        className="min-h-6 text-sm focus:outline-none"
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
        <p className="text-muted-foreground">
          Your queue is empty. Add videos from the feed, search or a watch page,
          or paste a link above. Videos leave the queue once you watch them to
          the end.
        </p>
      ) : (
        <>
          <ol className="flex flex-col divide-y" aria-label="Queue">
            {items.map((item, index) => (
              <QueueRow
                key={item.id}
                item={item}
                index={index}
                count={items.length}
                actions={actions}
              />
            ))}
          </ol>
          <p className="text-sm text-muted-foreground">
            Videos leave the queue once you watch them to the end.
          </p>
          <ClearQueue
            count={items.length}
            onCleared={() =>
              setStatus({ ok: true, message: "Cleared your queue." })
            }
          />
        </>
      )}
    </AppShell>
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
      statusRef.current?.focus();
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

function QueueRow({
  item,
  index,
  count,
  actions,
}: {
  item: QueueItem;
  index: number;
  count: number;
  actions: QueueActions;
}) {
  const title = itemTitle(item);
  const duration = formatDuration(item.duration_seconds);
  const params = { videoId: item.video_id };
  const isFirst = index === 0;
  const isLast = index === count - 1;
  const rowRef = useRef<HTMLLIElement>(null);

  // Keep keyboard focus on the row's controls as it moves: the browser drops
  // focus when the row's element is moved, and a button disables at the ends.
  function moveTo(position: number, fallback: "up" | "down") {
    const focused = document.activeElement;
    const action =
      focused instanceof HTMLElement && rowRef.current?.contains(focused)
        ? focused.dataset.action
        : undefined;
    actions.move(item, position);
    if (!action) return;
    requestAnimationFrame(() => {
      const row = rowRef.current;
      const target =
        row?.querySelector<HTMLButtonElement>(
          `button[data-action="${action}"]:not(:disabled)`,
        ) ??
        row?.querySelector<HTMLButtonElement>(
          `button[data-action="${fallback}"]:not(:disabled)`,
        );
      target?.focus();
    });
  }

  return (
    <li ref={rowRef} className="flex gap-4 py-3">
      <span
        className="w-6 shrink-0 pt-0.5 text-right text-muted-foreground tabular-nums"
        aria-hidden="true"
      >
        {index + 1}
      </span>
      {/* Mouse-only; the title link is the one in the tab order. */}
      <Link
        to="/watch/$videoId"
        params={params}
        tabIndex={-1}
        aria-hidden="true"
        className="relative aspect-video w-32 shrink-0 overflow-hidden rounded-lg bg-secondary"
      >
        {item.thumbnail_url && (
          <img
            src={item.thumbnail_url}
            alt=""
            loading="lazy"
            className="size-full rounded-[inherit] object-cover outline outline-1 -outline-offset-1 outline-black/10 dark:outline-white/10"
          />
        )}
      </Link>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <h3 className="font-medium break-words">
          <Link
            to="/watch/$videoId"
            params={params}
            className="hover:underline"
          >
            {title}
          </Link>
        </h3>
        <p className="flex flex-wrap gap-x-2 text-sm text-muted-foreground">
          {item.channel_title && <span>{item.channel_title}</span>}
          {duration && (
            <span className="tabular-nums">
              {item.channel_title && "· "}
              {duration}
            </span>
          )}
        </p>
        <div
          role="group"
          aria-label={`Reorder or remove ${title}`}
          className="flex flex-wrap gap-x-4 gap-y-1 text-sm"
        >
          <button
            type="button"
            data-action="top"
            disabled={isFirst}
            onClick={() => moveTo(0, "down")}
            aria-label={`Move ${title} to the top`}
            className="underline disabled:no-underline disabled:opacity-40"
          >
            Top
          </button>
          <button
            type="button"
            data-action="up"
            disabled={isFirst}
            onClick={() => moveTo(index - 1, "down")}
            aria-label={`Move ${title} up`}
            className="underline disabled:no-underline disabled:opacity-40"
          >
            Up
          </button>
          <button
            type="button"
            data-action="down"
            disabled={isLast}
            onClick={() => moveTo(index + 1, "up")}
            aria-label={`Move ${title} down`}
            className="underline disabled:no-underline disabled:opacity-40"
          >
            Down
          </button>
          <button
            type="button"
            onClick={() => actions.remove(item)}
            aria-label={`Remove ${title} from queue`}
            className="text-destructive underline"
          >
            Remove
          </button>
        </div>
      </div>
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
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <label htmlFor="queue-video" className="font-medium">
        Add a video
      </label>
      <div className="flex gap-2">
        <input
          id="queue-video"
          type="text"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="https://www.youtube.com/watch?v=…"
          required
          aria-invalid={error !== null || result?.ok === false}
          aria-describedby="queue-video-status"
          className="min-w-0 flex-1 rounded-lg border border-input bg-transparent outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 px-3 py-2"
        />
        <Button
          type="submit"
          variant="secondary"
          size="lg"
          disabled={mutation.isPending}
          className="px-4"
        >
          {mutation.isPending ? "Adding…" : "Add"}
        </Button>
      </div>
      <p id="queue-video-status" role="status" className="min-h-6 text-sm">
        {error && <span className="text-destructive">{error}</span>}
        {!error && mutation.isError && (
          <span className="text-destructive">
            Couldn't queue that. Try again later.
          </span>
        )}
        {!error && result?.ok === false && (
          <span className="text-destructive">{result.message}</span>
        )}
        {!error &&
          result?.ok === true &&
          (result.created
            ? `Added “${itemTitle(result.item)}”.`
            : `“${itemTitle(result.item)}” is already in your queue.`)}
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
      <div>
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="text-sm text-destructive underline"
        >
          Clear queue
        </button>
      </div>
    );
  }
  return (
    <div
      role="group"
      aria-label="Confirm clearing the queue"
      className="flex flex-wrap items-baseline gap-3 text-sm"
    >
      <span>
        Remove all {count} {count === 1 ? "video" : "videos"} from your queue?
      </span>
      <Button
        type="button"
        variant="destructive"
        size="sm"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
        className="px-3"
      >
        {mutation.isPending ? "Clearing…" : "Clear queue"}
      </Button>
      <button
        type="button"
        onClick={() => setConfirming(false)}
        className="underline"
      >
        Keep it
      </button>
      {mutation.isError && (
        <span role="alert" className="text-destructive">
          Couldn't clear the queue. Try again.
        </span>
      )}
    </div>
  );
}

function QueueError() {
  const router = useRouter();
  const queryErrorResetBoundary = useQueryErrorResetBoundary();

  useEffect(() => {
    queryErrorResetBoundary.reset();
  }, [queryErrorResetBoundary]);

  return (
    <AppShell className="flex max-w-4xl flex-col gap-6">
      <div role="alert" className="flex flex-col items-start gap-3">
        <p>Couldn't load your queue. The API may be down.</p>
        <button
          type="button"
          onClick={() => void router.invalidate()}
          className="underline"
        >
          Try again
        </button>
      </div>
    </AppShell>
  );
}
