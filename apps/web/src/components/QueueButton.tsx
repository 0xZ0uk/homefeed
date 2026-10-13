import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListMinus, ListPlus } from "lucide-react";
import { useState } from "react";

import { Button } from "#/components/ui/button";
import { cn } from "#/lib/utils";
import { dequeue, enqueueVideo, queueQuery } from "#/server/queue";

type QueueMessage = { ok: boolean; text: string };

/**
 * Whether a video is in the watch queue, and a toggle to add or remove it.
 * `message` is the last toggle's outcome, for a status region to announce.
 */
export function useQueueToggle(videoId: string) {
  const queryClient = useQueryClient();
  const { data: queue } = useQuery(queueQuery);
  const queued = queue?.find((item) => item.video_id === videoId);
  const [message, setMessage] = useState<QueueMessage | null>(null);
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queueQuery.queryKey });

  const add = useMutation({
    mutationFn: () => enqueueVideo({ data: { videoId } }),
    onSuccess: (result) =>
      setMessage(
        result.ok
          ? { ok: true, text: "Added to your queue." }
          : { ok: false, text: result.message },
      ),
    onError: () =>
      setMessage({ ok: false, text: "Couldn't queue that. Try again later." }),
    onSettled: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: number) => dequeue({ data: { id } }),
    onSuccess: () => setMessage({ ok: true, text: "Removed from your queue." }),
    onError: () =>
      setMessage({
        ok: false,
        text: "Couldn't remove that from the queue. Try again.",
      }),
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
        {queued ? <ListMinus /> : <ListPlus />}
        {queued ? "Remove from queue" : "Add to queue"}
      </Button>
      <QueueStatus message={message} />
    </span>
  );
}
