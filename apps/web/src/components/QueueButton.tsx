import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { dequeue, enqueueVideo, queueQuery } from "#/server/queue";

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
  const queryClient = useQueryClient();
  const { data: queue } = useQuery(queueQuery);
  const queued = queue?.find((item) => item.video_id === videoId);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
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
  const pending = add.isPending || remove.isPending;

  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-2">
      <button
        type="button"
        disabled={pending || queue === undefined}
        onClick={() => (queued ? remove.mutate(queued.id) : add.mutate())}
        aria-label={
          queued ? `Remove ${title} from queue` : `Add ${title} to queue`
        }
        className="underline disabled:opacity-50"
      >
        {queued ? "Remove from queue" : "Add to queue"}
      </button>
      <span role="status" className="text-gray-600">
        {message && (
          <span className={message.ok ? undefined : "text-red-600"}>
            {message.text}
          </span>
        )}
      </span>
    </span>
  );
}
