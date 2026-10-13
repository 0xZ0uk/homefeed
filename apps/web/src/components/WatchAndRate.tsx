import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useBlocker } from "@tanstack/react-router";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { Button } from "#/components/ui/button";
import { RatingPicker } from "#/components/RatingPicker";
import { VideoPlayer, type VideoPlayerHandle } from "#/components/VideoPlayer";
import { MAX_SCORE, MIN_SCORE, formatScore } from "#/lib/scores";
import type { WatchEvent } from "#/lib/player-events";
import { createWatchEventReporter, sendWatchEvent } from "#/lib/watch-reporter";
import { ratingQuery, removeRating, saveRating } from "#/server/ratings";

interface WatchAndRateProps {
  videoId: string;
  poster?: string | null;
  /** Where to resume, in seconds, or null to start from the beginning. */
  startAt?: number | null;
  /** Shown between the player and the rating, e.g. the video's title. */
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
 * The prompt appears once per visit:
 * - when the video ends, or
 * - when leaving the page through the app (a link, back/forward) after
 *   playing an unrated video: the navigation is held, the video paused, and
 *   it goes ahead once the prompt is answered or skipped ("Keep watching"
 *   cancels it).
 * Closing or reloading the tab can't show a prompt (browsers only allow their
 * own "leave site?" dialog, which would nag); the `close` event is still
 * recorded, and the rating stays editable here later.
 */
export function WatchAndRate({
  videoId,
  poster,
  startAt,
  children,
  aside,
  contentClassName,
}: WatchAndRateProps) {
  const queryClient = useQueryClient();
  const { data: rating, isError } = useQuery(ratingQuery(videoId));
  const score = rating?.score ?? null;
  const player = useRef<VideoPlayerHandle>(null);
  const [endedPrompt, setEndedPrompt] = useState(false);
  const [editing, setEditing] = useState(false);
  // Read by the navigation blocker, so kept in refs rather than state.
  const played = useRef(false);
  const answered = useRef(false);
  const rated = useRef(false);

  useEffect(() => {
    rated.current = score !== null;
  }, [score]);

  const reporter = useMemo(
    () =>
      createWatchEventReporter(videoId, (payload) => sendWatchEvent(payload)),
    [videoId],
  );

  const onWatchEvent = useCallback(
    (event: WatchEvent) => {
      reporter.report(event);
      if (event.type === "play") played.current = true;
      if (event.type === "ended" && !answered.current) setEndedPrompt(true);
    },
    [reporter],
  );

  const blocker = useBlocker({
    shouldBlockFn: ({ current, next }) =>
      current.pathname !== next.pathname &&
      played.current &&
      !answered.current &&
      !rated.current,
    enableBeforeUnload: false,
    withResolver: true,
  });
  const leaving = blocker.status === "blocked";

  useEffect(() => {
    if (leaving) player.current?.pause();
  }, [leaving]);

  const rate = async (picked: number) => {
    const saved = await saveRating({ data: { videoId, score: picked } });
    queryClient.setQueryData(ratingQuery(videoId).queryKey, saved);
  };

  const closePrompt = () => {
    answered.current = true;
    setEndedPrompt(false);
    if (blocker.status === "blocked") blocker.proceed();
  };

  const remove = async () => {
    await removeRating({ data: { videoId } });
    queryClient.setQueryData(ratingQuery(videoId).queryKey, null);
  };

  let panel;
  if (leaving || endedPrompt) {
    panel = (
      <RatingPicker
        key={leaving ? "leaving" : "ended"}
        title={leaving ? "Rate it before you go?" : "How was it?"}
        current={score}
        onRate={rate}
        onClose={closePrompt}
        skipLabel="Skip"
        submitLabel={
          leaving ? (score) => `Save ${score} and continue` : undefined
        }
        cancel={
          leaving
            ? { label: "Keep watching", onCancel: () => blocker.reset() }
            : undefined
        }
        autoFocus
      />
    );
  } else if (editing) {
    panel = (
      <RatingPicker
        title={score !== null ? "Change your rating" : "Rate this video"}
        current={score}
        onRate={rate}
        onClose={() => setEditing(false)}
        skipLabel="Cancel"
        autoFocus
      />
    );
  } else {
    panel = (
      <YourRating
        score={score}
        loadFailed={isError}
        onEdit={() => setEditing(true)}
        onRemove={remove}
        onRestore={rate}
      />
    );
  }

  return (
    <VideoPlayer
      ref={player}
      videoId={videoId}
      poster={poster}
      startAt={startAt}
      onWatchEvent={onWatchEvent}
    >
      {(notices) => (
        <div className={contentClassName}>
          <div className="flex min-w-0 flex-col gap-4">
            {notices}
            {children}
            {panel}
          </div>
          {aside}
        </div>
      )}
    </VideoPlayer>
  );
}

function YourRating({
  score,
  loadFailed,
  onEdit,
  onRemove,
  onRestore,
}: {
  score: number | null;
  loadFailed: boolean;
  onEdit: () => void;
  onRemove: () => Promise<void>;
  onRestore: (score: number) => Promise<void>;
}) {
  const [error, setError] = useState<string | null>(null);

  // The score that was just removed, so it can be put back.
  const [removed, setRemoved] = useState<number | null>(null);

  const remove = async () => {
    if (score === null) return;
    const previous = score;
    setError(null);
    try {
      await onRemove();
      setRemoved(previous);
    } catch {
      setError("Couldn't remove the rating. Try again.");
    }
  };

  const undo = async () => {
    if (removed === null) return;
    setError(null);
    try {
      await onRestore(removed);
      setRemoved(null);
    } catch {
      setError("Couldn't restore the rating. Try again.");
    }
  };

  // Rating again (score is set) retires the undo.
  const undoable = score === null ? removed : null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl bg-secondary p-3">
      <p className="mr-auto">
        {score !== null ? (
          <>
            Your rating:{" "}
            <strong className="text-lg tabular-nums">
              {formatScore(score)}
            </strong>
            <span
              aria-hidden="true"
              className="relative mx-3 inline-block h-1.5 w-24 rounded-full bg-[linear-gradient(to_right_in_oklch,var(--score-low),var(--score-mid),var(--score-high))] align-middle"
            >
              <span
                className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background bg-foreground shadow-sm"
                style={{
                  left: `${((score - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)) * 100}%`,
                }}
              />
            </span>
          </>
        ) : loadFailed ? (
          "Couldn't load your rating."
        ) : (
          "Not rated yet."
        )}
      </p>
      <Button
        type="button"
        variant="outline"
        size="lg"
        className="px-4"
        onClick={onEdit}
      >
        {score !== null ? "Change" : "Rate"}
      </Button>
      {score !== null && (
        <Button
          type="button"
          variant="ghost"
          size="lg"
          className="px-4"
          onClick={() => void remove()}
        >
          Remove rating
        </Button>
      )}
      <p role="status" className="text-sm text-muted-foreground">
        {undoable !== null && (
          <>
            Rating removed.{" "}
            <Button
              type="button"
              variant="link"
              className="h-auto p-0"
              onClick={() => void undo()}
            >
              Undo
            </Button>
          </>
        )}
      </p>
      {error && (
        <p role="alert" className="w-full text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
