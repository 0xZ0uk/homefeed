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

import { RatingPicker } from "#/components/RatingPicker";
import { ScoreScale } from "#/components/ScoreScale";
import { VideoPlayer, type VideoPlayerHandle } from "#/components/VideoPlayer";
import type { Chapter } from "#/lib/chapters";
import { scoreText } from "#/lib/scores";
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
 * The rating, always on the page right under the player. Picking a face saves
 * it at once, picking the lit face again removes the rating, and picking
 * another changes it. The scale shows the latest pick straight away; saves run
 * one at a time, in order, so the last pick is the one that sticks.
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
      <ScoreScale
        value={shown}
        onPick={pick}
        label="Rate this video"
        className="w-full max-w-xl"
      />
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
