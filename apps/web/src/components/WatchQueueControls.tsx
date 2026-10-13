import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { QueueButton } from "#/components/QueueButton";
import { nextInQueue } from "#/lib/queue";
import { queueQuery } from "#/server/queue";

/**
 * The watch page's queue controls: add or remove this video, and a link to
 * what's next in the queue. Nothing plays next on its own.
 */
export function WatchQueueControls({
  videoId,
  title,
}: {
  videoId: string;
  title: string;
}) {
  const { data: queue } = useQuery(queueQuery);
  const next = queue ? nextInQueue(queue, videoId) : null;

  return (
    <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
      <QueueButton videoId={videoId} title={title} />
      {next && (
        <p className="min-w-0 text-gray-600">
          Next in your{" "}
          <Link to="/queue" className="underline">
            queue
          </Link>
          :{" "}
          <Link
            to="/watch/$videoId"
            params={{ videoId: next.video_id }}
            className="font-medium text-gray-900 underline"
          >
            {next.title ?? next.video_id}
          </Link>
        </p>
      )}
    </div>
  );
}
