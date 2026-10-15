import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Clock, ClockCheck, Star, ThumbsDown, ThumbsUp } from "lucide-react";
import { useId, useState } from "react";

import { useQueueToggle } from "#/components/QueueButton";
import { ScoreFace } from "#/components/ScoreFace";
import { ScoreScale } from "#/components/ScoreScale";
import { Button } from "#/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTitle,
  PopoverTrigger,
} from "#/components/ui/popover";
import { ratedLabel } from "#/lib/card";
import { SCORE_SCALE_HINT } from "#/lib/scores";
import {
  UNDONE_MESSAGE,
  queuedMessage,
  type ActionStatus,
} from "#/lib/card-actions";
import {
  LESS_LIKE_THIS,
  MORE_LIKE_THIS,
  feedbackMessage,
  nextSignal,
  signalOf,
  type Signal,
} from "#/lib/feedback";
import { cn } from "#/lib/utils";
import { saveFeedback } from "#/server/feeds";
import { dequeue, enqueueVideo, queueQuery } from "#/server/queue";

/**
 * Saving "more like this" and "less like this" for videos. Pressing a signal
 * sets it at once (`apply` shows it wherever the video is on screen), says so
 * in the status line with an Undo, and saves it in the background. Saves run
 * one at a time, in order, so the last press is the one that sticks. When
 * saving fails, the earlier signal is shown again and `reload` loads what the
 * server holds, as a failed request doesn't say whether it got there.
 *
 * Returns what a card calls when one of its two buttons is pressed.
 */
export function useFeedbackToggle({
  apply,
  reload,
  announce,
}: {
  /** Shows a signal for a video wherever it is on screen. */
  apply: (videoId: string, signal: Signal | null) => void | Promise<void>;
  /** Loads again whatever shows feedback. */
  reload: () => void;
  announce: (status: ActionStatus) => void;
}) {
  const mutation = useMutation({
    scope: { id: "video-feedback" },
    mutationFn: ({ videoId, signal }: FeedbackChange) =>
      saveFeedback({ data: { videoId, signal } }),
    onMutate: ({ videoId, signal }) => apply(videoId, signal),
    onError: async (_error, { videoId, title, before }) => {
      await apply(videoId, before);
      announce({
        ok: false,
        message: `Couldn't save that for “${title}”. Try pressing it again.`,
      });
      reload();
    },
  });

  function change(
    video: FeedbackVideo,
    signal: Signal | null,
    undoing: boolean,
  ) {
    const before = signalOf(video.feedback);
    mutation.mutate({
      videoId: video.video_id,
      title: video.title,
      signal,
      before,
    });
    announce(
      undoing
        ? { ok: true, message: UNDONE_MESSAGE, focus: true }
        : {
            ok: true,
            message: feedbackMessage(video.title, signal, before),
            undo: () => change({ ...video, feedback: signal }, before, true),
          },
    );
  }

  return (video: FeedbackVideo, pressed: Signal) =>
    change(video, nextSignal(signalOf(video.feedback), pressed), false);
}

/**
 * A video's place in the watch queue, for the "Later" button: whether it's
 * queued and a toggle, as `useQueueToggle` has them. What a press did is said
 * in the status line, with an Undo that puts it back: it takes the added item
 * off the queue by its id, or adds the video again, whatever state the queue is
 * in by then.
 */
export function useLater(
  video: { video_id: string; title: string },
  announce: (status: ActionStatus) => void,
) {
  const queryClient = useQueryClient();
  const undo = useMutation({
    mutationFn: async ({
      added,
      itemId,
    }: {
      added: boolean;
      itemId: number | null;
    }) => {
      if (!added) {
        const result = await enqueueVideo({
          data: { videoId: video.video_id },
        });
        if (!result.ok) throw new Error(result.message);
      } else if (itemId !== null) {
        await dequeue({ data: { id: itemId } });
      }
    },
    onSuccess: () =>
      announce({ ok: true, message: UNDONE_MESSAGE, focus: true }),
    onError: () =>
      announce({ ok: false, message: "Couldn't undo that. Try again." }),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: queueQuery.queryKey }),
  });
  return useQueueToggle(video.video_id, ({ ok, added, text, itemId }) => {
    if (!ok) return announce({ ok: false, message: text });
    announce({
      ok: true,
      message: queuedMessage(video.title, added),
      undo: () => undo.mutate({ added, itemId }),
    });
  });
}

/** The video whose feedback is changed: what it has now, and its title. */
interface FeedbackVideo {
  video_id: string;
  title: string;
  feedback: number | null;
}

interface FeedbackChange {
  videoId: string;
  title: string;
  signal: Signal | null;
  /** What the video had before, to go back to if saving fails. */
  before: Signal | null;
}

/** The toggles' look: pressed ones are filled in, not just recoloured. */
const TOGGLE =
  "relative z-10 aria-pressed:border-primary aria-pressed:bg-primary aria-pressed:text-primary-foreground aria-pressed:hover:bg-primary aria-pressed:hover:text-primary-foreground";

/** A half of the joined "More" and "Less" control, on its shared fill. */
const HALF =
  "hover:bg-accent dark:hover:bg-accent aria-pressed:dark:hover:bg-primary";

/**
 * A card's quick actions, always visible and on one row: "More" and "Less"
 * (like this), joined as one control, steer the ranking and are pressed while
 * they apply (pressing the pressed one clears it); "Later" puts the video in
 * the watch queue and stays pressed while it's there. Each button's name says
 * it in full and names the video for screen readers.
 */
export function CardActions({
  title,
  feedback,
  onFeedback,
  queue,
}: {
  title: string;
  /** The video's feedback now. */
  feedback: number | null;
  onFeedback: (pressed: Signal) => void;
  queue: ReturnType<typeof useQueueToggle>;
}) {
  const signal = signalOf(feedback);
  return (
    <div className="flex items-center gap-2">
      <div className="flex rounded-full bg-secondary">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-pressed={signal === MORE_LIKE_THIS}
          onClick={() => onFeedback(MORE_LIKE_THIS)}
          className={cn(TOGGLE, HALF, "rounded-e-none ps-2.5 pe-2")}
        >
          <ThumbsUp
            aria-hidden="true"
            className={cn(signal === MORE_LIKE_THIS && "fill-current")}
          />
          More<span className="sr-only"> like this: {title}</span>
        </Button>
        <span aria-hidden="true" className="my-1.5 w-px bg-border" />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-pressed={signal === LESS_LIKE_THIS}
          onClick={() => onFeedback(LESS_LIKE_THIS)}
          className={cn(TOGGLE, HALF, "rounded-s-none ps-2 pe-2.5")}
        >
          <ThumbsDown
            aria-hidden="true"
            className={cn(signal === LESS_LIKE_THIS && "fill-current")}
          />
          Less<span className="sr-only"> like this: {title}</span>
        </Button>
      </div>
      <Button
        type="button"
        variant="secondary"
        size="sm"
        aria-pressed={queue.queued}
        // Not `disabled`: that would take focus away while a save is running.
        aria-disabled={!queue.ready || undefined}
        onClick={() => {
          if (queue.ready) queue.toggle();
        }}
        className={cn(TOGGLE, "hover:bg-accent")}
      >
        {queue.queued ? (
          <ClockCheck aria-hidden="true" />
        ) : (
          <Clock aria-hidden="true" />
        )}
        Later<span className="sr-only">: {title}</span>
      </Button>
    </div>
  );
}

/**
 * The button on a watched video's card to rate it, and then to change that
 * rating, sitting on the thumbnail beside "Watched": "Rate it", or once rated
 * the rating's face and number (named "You rated it 8"). It opens a popover
 * with the rating scale and what its ends mean; picking a face rates the
 * video and closes it.
 */
export function RateButton({
  title,
  rating,
  onRate,
}: {
  title: string;
  /** The video's rating, if it has one. */
  rating: number | null;
  onRate: (score: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const hintId = useId();
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            variant="ghost"
            size="xs"
            className="relative z-10 bg-black/80 ps-1 text-white hover:bg-black hover:text-white aria-expanded:bg-black aria-expanded:text-white dark:hover:bg-black"
          />
        }
        aria-label={
          rating === null ? undefined : `${ratedLabel(rating)}: ${title}`
        }
      >
        {rating === null ? (
          <>
            <Star aria-hidden="true" className="ms-0.5" />
            Rate it<span className="sr-only">: {title}</span>
          </>
        ) : (
          <>
            <ScoreFace score={rating} filled className="size-4.5" />
            <span className="tabular-nums">{rating}</span>
          </>
        )}
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="start"
        className="w-80 max-w-[calc(100vw-2rem)] gap-0 p-3 motion-reduce:data-open:animate-none motion-reduce:data-closed:animate-none"
      >
        <PopoverTitle className="text-sm font-semibold">
          How was it?
        </PopoverTitle>
        <p id={hintId} className="text-xs text-muted-foreground">
          {SCORE_SCALE_HINT}
        </p>
        <ScoreScale
          value={rating}
          label={`Rate “${title}”`}
          describedBy={hintId}
          onPick={(score) => {
            setOpen(false);
            if (score !== rating) onRate(score);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}
