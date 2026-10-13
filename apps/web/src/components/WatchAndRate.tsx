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
import { VideoPlayer, type VideoPlayerHandle } from "#/components/VideoPlayer";
import type { Grade } from "#/lib/grades";
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
}: WatchAndRateProps) {
  const queryClient = useQueryClient();
  const { data: rating, isError } = useQuery(ratingQuery(videoId));
  const grade = rating?.grade ?? null;
  const player = useRef<VideoPlayerHandle>(null);
  const [endedPrompt, setEndedPrompt] = useState(false);
  const [editing, setEditing] = useState(false);
  // Read by the navigation blocker, so kept in refs rather than state.
  const played = useRef(false);
  const answered = useRef(false);
  const rated = useRef(false);

  useEffect(() => {
    rated.current = grade !== null;
  }, [grade]);

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

  const rate = async (picked: Grade) => {
    const saved = await saveRating({ data: { videoId, grade: picked } });
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
        current={grade}
        onRate={rate}
        onClose={closePrompt}
        skipLabel="Skip"
        doneLabel={leaving ? "Continue" : "Done"}
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
        title={grade ? "Change your rating" : "Rate this video"}
        current={grade}
        onRate={rate}
        onClose={() => setEditing(false)}
        skipLabel="Cancel"
        autoFocus
      />
    );
  } else {
    panel = (
      <YourRating
        grade={grade}
        loadFailed={isError}
        onEdit={() => setEditing(true)}
        onRemove={remove}
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <VideoPlayer
        ref={player}
        videoId={videoId}
        poster={poster}
        startAt={startAt}
        onWatchEvent={onWatchEvent}
      />
      {children}
      {panel}
    </div>
  );
}

function YourRating({
  grade,
  loadFailed,
  onEdit,
  onRemove,
}: {
  grade: Grade | null;
  loadFailed: boolean;
  onEdit: () => void;
  onRemove: () => Promise<void>;
}) {
  const [error, setError] = useState<string | null>(null);

  const remove = async () => {
    setError(null);
    try {
      await onRemove();
    } catch {
      setError("Couldn't remove the rating. Try again.");
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl bg-secondary/60 px-4 py-3">
      <p className="mr-auto">
        {grade ? (
          <>
            Your rating: <strong className="text-lg">{grade}</strong>
          </>
        ) : loadFailed ? (
          "Couldn't load your rating."
        ) : (
          "Not rated yet."
        )}
      </p>
      <button
        type="button"
        className="inline-flex h-9 items-center justify-center rounded-full bg-secondary px-4 text-sm font-medium hover:bg-accent disabled:opacity-50"
        onClick={onEdit}
      >
        {grade ? "Change" : "Rate"}
      </button>
      {grade && (
        <button
          type="button"
          className="inline-flex h-9 items-center justify-center rounded-full px-4 text-sm font-medium hover:bg-accent"
          onClick={() => void remove()}
        >
          Remove rating
        </button>
      )}
      {error && (
        <p role="alert" className="w-full text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
