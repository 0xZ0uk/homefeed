import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";

import {
  CardActions,
  useFeedbackToggle,
  useLater,
} from "#/components/CardActions";
import { VideoCard } from "#/components/VideoCard";
import { Button } from "#/components/ui/button";
import type { ActionStatus } from "#/lib/card-actions";
import { withFeedback, type Signal } from "#/lib/feedback";
import { nextFeedText } from "#/lib/today";
import { cn } from "#/lib/utils";
import { WILDCARDS_LIMIT, wildcardsQuery, type Wildcard } from "#/server/feeds";
import { settingsQuery } from "#/server/settings";

/**
 * The end of today's feed, after the last card and once "Show more" has
 * nothing more: "That's today.", when the next feed comes and a button that
 * shows a few wildcards, videos from outside the topics I follow. Nothing
 * suggests more on its own: the wildcards are only fetched when the button is
 * pressed, and then shown as cards, each saying why it's here.
 *
 * What the cards' quick actions did is said in the feed's status line
 * (`announce`); what asking for the wildcards did is said in a status line of
 * its own, which is on the page, empty, from the start.
 *
 * It takes over from buttons that are gone: the block appears in place of the
 * "Show more" that was pressed, so focus moves to its heading, and the
 * wildcards appear in place of the button that asked for them, so focus moves
 * to the status line above them, from where the first card is next.
 */
export function FeedEnd({
  now,
  announce,
}: {
  now: Date;
  announce: (status: ActionStatus) => void;
}) {
  const headingId = useId();
  const hintId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const statusRef = useRef<HTMLParagraphElement>(null);
  const queryClient = useQueryClient();
  const [asked, setAsked] = useState(false);
  const { data: settings } = useQuery(settingsQuery);
  const wildcards = useQuery({ ...wildcardsQuery, enabled: asked });
  const toggleFeedback = useFeedbackToggle({
    apply: async (videoId, signal) => {
      await queryClient.cancelQueries({ queryKey: wildcardsQuery.queryKey });
      queryClient.setQueryData(wildcardsQuery.queryKey, (shown) =>
        shown ? withFeedback(shown, videoId, signal) : shown,
      );
    },
    reload: () =>
      queryClient.invalidateQueries({ queryKey: wildcardsQuery.queryKey }),
    announce,
  });

  const shown = asked && wildcards.isSuccess ? wildcards.data : null;
  const arrived = shown !== null;
  const loading = asked && wildcards.isFetching;
  const failed = asked && wildcards.isError && !loading;
  let message: string | null = null;
  if (failed) message = "Couldn't load wildcards. Try again.";
  else if (shown?.length === 0) {
    message =
      "No wildcards today: nothing outside the topics you follow is waiting. Check back after the next feed.";
  } else if (shown) {
    message = `Added ${shown.length} ${shown.length === 1 ? "wildcard" : "wildcards"} below.`;
  }
  useEffect(() => headingRef.current?.focus(), []);
  useEffect(() => {
    if (arrived) statusRef.current?.focus();
  }, [arrived]);
  const nextFeed =
    settings &&
    nextFeedText(
      settings.values.feed_refresh_time,
      now,
      settings.values.timezone ?? settings.system_timezone,
    );

  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-4 border-t pt-8 pb-6"
    >
      <div className="flex flex-col gap-1">
        <h2
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="w-fit rounded-sm text-xl font-bold outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          That's today.
        </h2>
        <p className="text-muted-foreground">
          You've seen everything the feed found.
          {nextFeed && ` ${nextFeed}.`}
        </p>
      </div>
      {shown === null && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button
            type="button"
            variant="secondary"
            // Not `disabled`: that would take focus away while it loads.
            aria-disabled={loading || undefined}
            aria-describedby={hintId}
            onClick={() => {
              if (loading) return;
              if (asked) void wildcards.refetch();
              else setAsked(true);
            }}
            className="rounded-lg px-6"
          >
            {loading
              ? "Finding wildcards…"
              : `Show ${WILDCARDS_LIMIT} wildcards`}
          </Button>
          <p id={hintId} className="text-sm text-muted-foreground">
            Wildcards are videos from outside the topics you follow.
          </p>
        </div>
      )}
      <p
        ref={statusRef}
        role="status"
        tabIndex={-1}
        className={cn(
          "w-fit rounded-sm text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50 empty:sr-only",
          failed ? "text-destructive" : "text-muted-foreground",
        )}
      >
        {message}
      </p>
      {shown && shown.length > 0 && (
        <ol
          aria-label="Wildcards"
          className="grid grid-cols-1 gap-x-4 gap-y-10 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4"
        >
          {shown.map((video) => (
            <WildcardCard
              key={video.video_id}
              video={video}
              now={now}
              onFeedback={toggleFeedback}
              announce={announce}
            />
          ))}
        </ol>
      )}
    </section>
  );
}

/**
 * A wildcard as a card: its topic tags, an (i) button with why it's here
 * ("Wildcard: outside the topics you follow") and the score behind it, and the
 * quick actions to steer the feed from it.
 */
function WildcardCard({
  video,
  now,
  onFeedback,
  announce,
}: {
  video: Wildcard;
  now: Date;
  onFeedback: (video: Wildcard, pressed: Signal) => void;
  announce: (status: ActionStatus) => void;
}) {
  const queue = useLater(video, announce);
  return (
    <VideoCard
      video={{ ...video, watched: false }}
      now={now}
      actions={
        <CardActions
          title={video.title}
          feedback={video.feedback}
          onFeedback={(pressed) => onFeedback(video, pressed)}
          queue={queue}
        />
      }
    />
  );
}
