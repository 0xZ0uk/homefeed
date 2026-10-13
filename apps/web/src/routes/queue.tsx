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

import { AppHeader } from "#/components/AppHeader";
import { showsThumbnails, type DisplayPrefs } from "#/lib/display";
import { formatDuration } from "#/lib/format";
import { parseVideoInput, withItemMoved, withoutItem } from "#/lib/queue";
import { displayPrefsQuery } from "#/server/display";
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
    Promise.all([
      queryClient.ensureQueryData(queueQuery),
      queryClient.ensureQueryData(displayPrefsQuery),
    ]),
  component: Queue,
  errorComponent: QueueError,
});

type Status = { ok: boolean; message: string };

function Queue() {
  const { data: items } = useSuspenseQuery(queueQuery);
  const { data: display } = useSuspenseQuery(displayPrefsQuery);
  const [status, setStatus] = useState<Status | null>(null);
  const statusRef = useRef<HTMLParagraphElement>(null);
  const actions = useQueueActions(setStatus, statusRef);
  const first = items[0];

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <AppHeader />
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <h2 className="text-xl font-semibold">
          Queue
          {items.length > 0 && (
            <span className="font-normal text-gray-600">
              {" "}
              · {items.length} {items.length === 1 ? "video" : "videos"}
            </span>
          )}
        </h2>
        {first && (
          <Link
            to="/watch/$videoId"
            params={{ videoId: first.video_id }}
            className="rounded bg-black px-3 py-2 font-medium text-white"
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
          <span className={status.ok ? "text-gray-600" : "text-red-600"}>
            {status.message}
          </span>
        )}
      </p>
      {items.length === 0 ? (
        <p className="text-gray-600">
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
                display={display}
                actions={actions}
              />
            ))}
          </ol>
          <p className="text-sm text-gray-600">
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
    </main>
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
  display,
  actions,
}: {
  item: QueueItem;
  index: number;
  count: number;
  display: DisplayPrefs;
  actions: QueueActions;
}) {
  const title = itemTitle(item);
  const duration = formatDuration(item.duration_seconds);
  const thumbnails = showsThumbnails(display);
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
        className="w-6 shrink-0 pt-0.5 text-right text-gray-500 tabular-nums"
        aria-hidden="true"
      >
        {index + 1}
      </span>
      {thumbnails && (
        // Mouse-only; the title link is the one in the tab order.
        <Link
          to="/watch/$videoId"
          params={params}
          tabIndex={-1}
          aria-hidden="true"
          className="relative aspect-video w-32 shrink-0 overflow-hidden rounded bg-gray-200"
        >
          {item.thumbnail_url && (
            <img
              src={item.thumbnail_url}
              alt=""
              loading="lazy"
              className="size-full object-cover"
            />
          )}
        </Link>
      )}
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
        <p className="flex flex-wrap gap-x-2 text-sm text-gray-600">
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
            className="text-red-700 underline"
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
          className="min-w-0 flex-1 rounded border px-3 py-2"
        />
        <button
          type="submit"
          disabled={mutation.isPending}
          className="rounded border px-3 py-2 font-medium disabled:opacity-50"
        >
          {mutation.isPending ? "Adding…" : "Add"}
        </button>
      </div>
      <p id="queue-video-status" role="status" className="min-h-6 text-sm">
        {error && <span className="text-red-600">{error}</span>}
        {!error && mutation.isError && (
          <span className="text-red-600">
            Couldn't queue that. Try again later.
          </span>
        )}
        {!error && result?.ok === false && (
          <span className="text-red-600">{result.message}</span>
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
          className="text-sm text-red-700 underline"
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
      <button
        type="button"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
        className="rounded bg-red-700 px-2 py-1 font-medium text-white disabled:opacity-50"
      >
        {mutation.isPending ? "Clearing…" : "Clear queue"}
      </button>
      <button
        type="button"
        onClick={() => setConfirming(false)}
        className="underline"
      >
        Keep it
      </button>
      {mutation.isError && (
        <span role="alert" className="text-red-600">
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
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <AppHeader />
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
    </main>
  );
}
