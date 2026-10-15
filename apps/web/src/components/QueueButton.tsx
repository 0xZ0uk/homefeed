import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListMinus, ListPlus } from "lucide-react";
import { useState } from "react";

import { Button } from "#/components/ui/button";
import { cn } from "#/lib/utils";
import { dequeue, enqueueVideo, queueQuery } from "#/server/queue";

/** Stacked icons cross-fade; reduced motion keeps only the opacity fade. */
const ICON =
  "col-start-1 row-start-1 size-4 transition-[opacity,scale,filter] duration-300 ease-[cubic-bezier(0.2,0,0,1)]";
const ACTIVE = "opacity-100 motion-safe:scale-100 motion-safe:blur-none";
const INACTIVE = "opacity-0 motion-safe:scale-25 motion-safe:blur-xs";

type QueueMessage = { ok: boolean; text: string };

/**
 * What a toggle did: its message, whether it was adding to the queue, and the
 * queue item it added (null when it didn't add one).
 */
export type QueueResult = QueueMessage & {
  added: boolean;
  itemId: number | null;
};

/**
 * Whether a video is in the watch queue, and a toggle to add or remove it.
 * `message` is the last toggle's outcome, for a status region to announce;
 * `onResult` is told of each outcome as well, for a status elsewhere.
 */
export function useQueueToggle(
  videoId: string,
  onResult?: (result: QueueResult) => void,
) {
  const queryClient = useQueryClient();
  const { data: queue } = useQuery(queueQuery);
  const queued = queue?.find((item) => item.video_id === videoId);
  const [message, setMessage] = useState<QueueMessage | null>(null);
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queueQuery.queryKey });
  const report = (
    next: QueueMessage,
    added: boolean,
    itemId: number | null = null,
  ) => {
    setMessage(next);
    onResult?.({ ...next, added, itemId });
  };

  const add = useMutation({
    mutationFn: () => enqueueVideo({ data: { videoId } }),
    onSuccess: (result) =>
      report(
        result.ok
          ? { ok: true, text: "Added to your queue." }
          : { ok: false, text: result.message },
        true,
        result.ok ? result.item.id : null,
      ),
    onError: () =>
      report(
        { ok: false, text: "Couldn't queue that. Try again later." },
        true,
      ),
    onSettled: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: number) => dequeue({ data: { id } }),
    onSuccess: () =>
      report({ ok: true, text: "Removed from your queue." }, false),
    onError: () =>
      report(
        { ok: false, text: "Couldn't remove that from the queue. Try again." },
        false,
      ),
    onSettled: invalidate,
  });

  return {
    queued: queued !== undefined,
    /** False while the queue loads or a toggle is in flight. */
    ready: queue !== undefined && !add.isPending && !remove.isPending,
    message,
    toggle: () => (queued ? remove.mutate(queued.id) : add.mutate()),
  };
}

/** The outcome of a queue toggle, as a polite status message. */
export function QueueStatus({
  message,
  className,
}: {
  message: QueueMessage | null;
  className?: string;
}) {
  return (
    <span role="status" className={cn("text-muted-foreground", className)}>
      {message && (
        <span className={message.ok ? undefined : "text-destructive"}>
          {message.text}
        </span>
      )}
    </span>
  );
}

/**
 * Adds a video to the watch queue, or removes it when it's already queued.
 * The outcome is announced next to the button.
 */
export function QueueButton({
  videoId,
  title,
}: {
  videoId: string;
  title: string;
}) {
  const { queued, ready, message, toggle } = useQueueToggle(videoId);

  return (
    <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      <Button
        variant="secondary"
        disabled={!ready}
        onClick={toggle}
        aria-label={
          queued ? `Remove ${title} from queue` : `Add ${title} to queue`
        }
      >
        <span className="relative inline-grid size-4" aria-hidden="true">
          <ListPlus className={cn(ICON, queued ? INACTIVE : ACTIVE)} />
          <ListMinus className={cn(ICON, queued ? ACTIVE : INACTIVE)} />
        </span>
        {queued ? "Remove from queue" : "Add to queue"}
      </Button>
      <QueueStatus message={message} />
    </span>
  );
}
