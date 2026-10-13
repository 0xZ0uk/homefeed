import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ListVideo } from "lucide-react";

import { nextInQueue } from "#/lib/queue";
import { queueQuery } from "#/server/queue";

/**
 * The watch page's link to what's next in the queue, if anything. Nothing
 * plays next on its own: it's a link, not an autoplay.
 */
export function NextInQueue({ videoId }: { videoId: string }) {
  const { data: queue } = useQuery(queueQuery);
  const next = queue ? nextInQueue(queue, videoId) : null;
  if (!next) return null;

  return (
    <section
      aria-labelledby="next-in-queue"
      className="flex flex-col gap-1 rounded-xl border p-4"
    >
      <h3
        id="next-in-queue"
        className="flex items-center gap-2 text-sm text-muted-foreground"
      >
        <ListVideo className="size-4" />
        Next in your queue
      </h3>
      <Link
        to="/watch/$videoId"
        params={{ videoId: next.video_id }}
        className="line-clamp-2 font-medium hover:underline"
      >
        {next.title ?? next.video_id}
      </Link>
    </section>
  );
}
