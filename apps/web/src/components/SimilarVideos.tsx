import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { VideoCard } from "#/components/VideoCard";
import { Button } from "#/components/ui/button";
import {
  SIMILAR_FAILED,
  SIMILAR_NOTE,
  similarButtonLabel,
  similarStatus,
  similarView,
} from "#/lib/similar";
import { cn } from "#/lib/utils";
import { similarVideosQuery } from "#/server/videos";

/**
 * "More like this", under the watch page's description. Nothing similar is
 * looked up or shown until the button is pressed, and nothing is offered when
 * a video ends: it's a request, never a recommendation, and a line under the
 * heading says so. What comes back is a finite list of cards, each saying why
 * it's there ("Related on YouTube", "Similar to this video").
 */
export function SimilarVideos({ videoId }: { videoId: string }) {
  const [asked, setAsked] = useState(false);
  // No silent retries: a failure says so at once and the button tries again.
  const query = useQuery({
    ...similarVideosQuery(videoId),
    enabled: asked,
    retry: false,
  });
  // One "now" per render pass keeps every card's age consistent.
  const [now] = useState(() => new Date());
  const headingId = useId();
  const statusRef = useRef<HTMLParagraphElement>(null);
  const videos = query.data;
  const view = similarView(asked, {
    count: videos?.length ?? null,
    failed: query.isError,
  });
  const status = similarStatus(view, videos?.length ?? 0);
  const loading = view === "loading";
  const answered = view === "found" || view === "empty";

  // The button leaves with the answer: carry the keyboard to the message above
  // the list, which a screen reader then reads.
  useEffect(() => {
    if (answered) statusRef.current?.focus();
  }, [answered]);

  function ask() {
    if (loading) return;
    if (view === "failed") void query.refetch();
    else setAsked(true);
  }

  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-3 border-t pt-5"
    >
      <div className="flex flex-col gap-1">
        <h2 id={headingId} className="text-xl font-bold">
          More like this
        </h2>
        <p className="text-sm text-muted-foreground">{SIMILAR_NOTE}</p>
      </div>
      {!answered && (
        <Button
          type="button"
          variant="secondary"
          size="lg"
          // Not `disabled`, which would drop the keyboard while it looks.
          aria-disabled={loading || undefined}
          onClick={ask}
          className="self-start px-4 aria-disabled:opacity-50"
        >
          <Sparkles aria-hidden="true" />
          {similarButtonLabel(view)}
        </Button>
      )}
      {/* Always there, so screen readers are listening; out of sight while empty. */}
      <p
        ref={statusRef}
        role="status"
        tabIndex={-1}
        className={cn(
          "text-sm text-muted-foreground focus:outline-none",
          !status && "sr-only",
        )}
      >
        {status}
      </p>
      {view === "failed" && (
        <p role="alert" className="text-sm text-destructive">
          {SIMILAR_FAILED}
        </p>
      )}
      {view === "found" && videos && (
        <ol
          aria-label="Videos like this one"
          className="grid grid-cols-1 gap-x-4 gap-y-8 pt-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4"
        >
          {videos.map((video) => (
            <VideoCard
              key={video.video_id}
              video={video}
              now={now}
              overlay={
                <span className="absolute bottom-1.5 left-1.5 max-w-[calc(100%-5rem)] truncate rounded bg-black/80 px-1.5 py-px text-xs font-medium text-white">
                  {video.reason}
                </span>
              }
            />
          ))}
        </ol>
      )}
    </section>
  );
}
