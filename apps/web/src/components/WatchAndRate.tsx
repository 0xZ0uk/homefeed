import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  useCallback,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { RatingPicker } from "#/components/RatingPicker";
import { ScoreScale } from "#/components/ScoreScale";
import { VideoPlayer, type VideoPlayerHandle } from "#/components/VideoPlayer";
import type { Chapter } from "#/lib/chapters";
import { SCORE_SCALE_HINT, scoreText } from "#/lib/scores";
import type { WatchEvent } from "#/lib/player-events";
import { createWatchEventReporter, sendWatchEvent } from "#/lib/watch-reporter";
import { ratingQuery, removeRating, saveRating } from "#/server/ratings";

interface WatchAndRateProps {
  videoId: string;
  poster?: string | null;
  /** Where to resume, in seconds, or null to start from the beginning. */
  startAt?: number | null;
  /** Marked on the player's progress bar. */
  chapters?: readonly Chapter[];
  /** Shown below the rating, e.g. the video's title and details. */
  children?: ReactNode;
  /** Shown beside the info column on wide screens (xl). */
  aside?: ReactNode;
  /** Classes for the padded content area below the player. */
  contentClassName?: string;
}

/**
 * The player, its watch history and the rating prompt.
 *
 * Every play, pause, seek, end and close goes to `POST /watch-events`.
 * The prompt appears once per visit, when the video ends. The rating stays
 * editable under the player at any time.
 */
export function WatchAndRate({
  videoId,
  poster,
  startAt,
  chapters,
  children,
  aside,
  contentClassName,
}: WatchAndRateProps) {
  const queryClient = useQueryClient();
  const { data: rating, isError } = useQuery(ratingQuery(videoId));
  const score = rating?.score ?? null;
  const player = useRef<VideoPlayerHandle>(null);
  const [endedPrompt, setEndedPrompt] = useState(false);
  const answered = useRef(false);

  const reporter = useMemo(
    () =>
      createWatchEventReporter(videoId, (payload) => sendWatchEvent(payload)),
    [videoId],
  );

  const onWatchEvent = useCallback(
    (event: WatchEvent) => {
      reporter.report(event);
      if (event.type === "ended" && !answered.current) setEndedPrompt(true);
    },
    [reporter],
  );

  const rate = async (picked: number) => {
    const saved = await saveRating({ data: { videoId, score: picked } });
    queryClient.setQueryData(ratingQuery(videoId).queryKey, saved);
  };

  const closePrompt = () => {
    answered.current = true;
    setEndedPrompt(false);
  };

  const remove = async () => {
    await removeRating({ data: { videoId } });
    queryClient.setQueryData(ratingQuery(videoId).queryKey, null);
  };

  let panel;
  if (endedPrompt) {
    panel = (
      <RatingPicker
        title="How was it?"
        current={score}
        onRate={rate}
        onClose={closePrompt}
        skipLabel="Skip"
        autoFocus
      />
    );
  } else {
    panel = (
      <InlineRating
        score={score}
        loadFailed={isError}
        onRate={rate}
        onRemove={remove}
      />
    );
  }

  return (
    <VideoPlayer
      ref={player}
      videoId={videoId}
      poster={poster}
      startAt={startAt}
      chapters={chapters}
      onWatchEvent={onWatchEvent}
    >
      {(notices) => (
        <div className={contentClassName}>
          <div className="flex min-w-0 flex-col gap-4">
            {notices}
            {panel}
            {children}
          </div>
          {aside}
        </div>
      )}
    </VideoPlayer>
  );
}

/**
 * The rating, always on the page right under the player, with its label and a
 * hint of what the ends of the scale mean. Picking a face saves it at once,
 * picking the lit face again removes the rating, and picking another changes
 * it. The scale shows the latest pick straight away; saves run one at a time,
 * in order, so the last pick is the one that sticks.
 */
function InlineRating({
  score,
  loadFailed,
  onRate,
  onRemove,
}: {
  score: number | null;
  loadFailed: boolean;
  onRate: (score: number) => Promise<void>;
  onRemove: () => Promise<void>;
}) {
  // The latest pick while its save is queued or running (null: removed);
  // undefined when nothing is pending, so the stored score shows.
  const [intent, setIntent] = useState<number | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const queue = useRef(Promise.resolve());
  const pending = useRef(0);
  const shown = intent === undefined ? score : intent;
  const labelId = useId();
  const hintId = useId();

  const pick = (picked: number) => {
    const next = picked === shown ? null : picked;
    setIntent(next);
    setError(null);
    pending.current += 1;
    queue.current = queue.current.then(async () => {
      try {
        if (next === null) await onRemove();
        else await onRate(next);
        setAnnouncement(
          next === null ? "Rating removed" : `Rated ${scoreText(next)}`,
        );
      } catch {
        setError(
          next === null
            ? "Couldn't remove the rating. Try again."
            : "Couldn't save the rating. Try again.",
        );
      } finally {
        pending.current -= 1;
        if (pending.current === 0) setIntent(undefined);
      }
    });
  };

  return (
    <div className="flex flex-col items-center gap-1">
      {loadFailed && score === null && (
        <p className="text-sm text-muted-foreground">
          Couldn&apos;t load your rating.
        </p>
      )}
      <div className="flex w-full max-w-xl flex-col">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4">
          <p id={labelId} className="font-medium">
            Rate this video
          </p>
          <p id={hintId} className="text-sm text-muted-foreground">
            {SCORE_SCALE_HINT}
          </p>
        </div>
        <ScoreScale
          value={shown}
          onPick={pick}
          label="Rate this video"
          labelledBy={labelId}
          describedBy={hintId}
        />
      </div>
      <p role="status" className="sr-only">
        {announcement}
      </p>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
