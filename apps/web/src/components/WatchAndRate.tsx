import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useBlocker } from "@tanstack/react-router";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

import { Button } from "#/components/ui/button";
import { RatingPicker, UNRATED_START } from "#/components/RatingPicker";
import { ScoreSlider } from "#/components/ScoreSlider";
import { VideoPlayer, type VideoPlayerHandle } from "#/components/VideoPlayer";
import { formatScore } from "#/lib/scores";
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

/**
 * The rating, always on the page: the slider sits at the saved score (or the
 * middle of the scale, unrated), and moving it offers Save and Reset. A saved
 * rating can be removed, with an Undo.
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
  const headingId = useId();
  const [draft, setDraft] = useState(score ?? UNRATED_START);
  const [saved, setSaved] = useState(score);
  if (score !== saved) {
    // The stored score changed (saved here, in a prompt or removed): follow it.
    setSaved(score);
    setDraft(score ?? UNRATED_START);
  }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The score that was just removed, so it can be put back.
  const [removed, setRemoved] = useState<number | null>(null);

  const run = async (action: () => Promise<void>, failure: string) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch {
      setError(failure);
    } finally {
      setBusy(false);
    }
  };

  const save = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      await onRate(draft);
      setRemoved(null);
    }, "Couldn't save the rating. Try again.");
  };

  const remove = () => {
    if (score === null) return;
    const previous = score;
    void run(async () => {
      await onRemove();
      setRemoved(previous);
    }, "Couldn't remove the rating. Try again.");
  };

  const undo = () => {
    if (removed === null) return;
    const previous = removed;
    void run(async () => {
      await onRate(previous);
      setRemoved(null);
    }, "Couldn't restore the rating. Try again.");
  };

  const changed = score === null || draft !== score;
  // Rating again retires the undo.
  const undoable = score === null ? removed : null;

  return (
    <form
      aria-labelledby={headingId}
      onSubmit={save}
      className="flex flex-col gap-2 rounded-xl bg-secondary p-3"
    >
      <h3 id={headingId} className="font-semibold">
        {score !== null ? (
          <>
            Your rating:{" "}
            <span className="tabular-nums">{formatScore(score)}</span>
          </>
        ) : loadFailed ? (
          "Couldn't load your rating"
        ) : (
          "Rate this video"
        )}
      </h3>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <ScoreSlider
          value={draft}
          onValueChange={setDraft}
          label="Score"
          disabled={busy}
          className="max-w-xl min-w-60 grow pt-6"
        />
        <div className="flex flex-wrap items-center gap-2">
          {changed ? (
            <>
              <Button
                type="submit"
                size="lg"
                className="px-4 tabular-nums"
                disabled={busy}
              >
                Save {formatScore(draft)}
              </Button>
              {score !== null && (
                <Button
                  type="button"
                  variant="ghost"
                  size="lg"
                  className="px-4"
                  disabled={busy}
                  onClick={() => setDraft(score)}
                >
                  Reset
                </Button>
              )}
            </>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="lg"
              className="px-4"
              disabled={busy}
              onClick={remove}
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
                  disabled={busy}
                  onClick={undo}
                >
                  Undo
                </Button>
              </>
            )}
          </p>
        </div>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </form>
  );
}
