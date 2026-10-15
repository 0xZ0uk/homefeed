import { useQuery } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type ReactNode,
  type Ref,
} from "react";

import { useRegisterPlayerMedia } from "#/components/PlayerMedia";
import { SponsorSkip } from "#/components/SponsorSkip";
import type { ShakaPlayer } from "#/components/player/media-state";
import { PlayerControls } from "#/components/player/PlayerControls";
import type { Chapter } from "#/lib/chapters";
import {
  trackWatchEvents,
  watchPosition,
  type WatchEventListener,
} from "#/lib/player-events";
import {
  sponsorSegmentsQuery,
  type SponsorSegment,
} from "#/server/video-extras";
import { manifestUrl } from "#/server/videos";

/** Control over the player for the page around it (e.g. the rating prompt, #15). */
export interface VideoPlayerHandle {
  /** Current playback position in seconds. */
  getPosition: () => number;
  /** Duration in seconds, or null until the manifest has loaded. */
  getDuration: () => number | null;
  pause: () => void;
}

interface VideoPlayerProps {
  videoId: string;
  poster?: string | null;
  /** Where to start, in seconds (the saved resume position); read once. */
  startAt?: number | null;
  /** Marked on the progress bar. */
  chapters?: readonly Chapter[];
  /** Play, pause, seek, end and close (leaving the page), with the position. */
  onWatchEvent?: WatchEventListener;
  ref?: Ref<VideoPlayerHandle>;
  /** Lays out what follows the player band; gets the error
   * message to place inside the padded content area. */
  children?: (notices: ReactNode) => ReactNode;
}

/**
 * Shaka Player over the video's DASH manifest, proxied through this app, with
 * YouTube-style controls: the progress bar marks chapters and the SponsorBlock
 * segments that get skipped.
 *
 * Playback only starts when the viewer presses play (no autoplay), and when the
 * video ends nothing else is offered or played.
 */
export function VideoPlayer({
  videoId,
  poster,
  startAt,
  chapters = NO_CHAPTERS,
  onWatchEvent,
  ref,
  children,
}: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [media, setMedia] = useState<HTMLVideoElement | null>(null);
  const attachVideo = useCallback((video: HTMLVideoElement | null) => {
    videoRef.current = video;
    setMedia(video);
  }, []);
  const [player, setPlayer] = useState<ShakaPlayer | null>(null);
  const { data: segments = NO_SEGMENTS } = useQuery(
    sponsorSegmentsQuery(videoId),
  );
  // Only the first value counts: a later one mustn't jump a playing video.
  const [initialStartAt] = useState(startAt);
  const listenerRef = useRef(onWatchEvent);
  const [error, setError] = useState<string | null>(null);
  useRegisterPlayerMedia(videoRef);

  useEffect(() => {
    listenerRef.current = onWatchEvent;
  }, [onWatchEvent]);

  useImperativeHandle(
    ref,
    () => ({
      getPosition: () =>
        videoRef.current ? watchPosition(videoRef.current) : 0,
      getDuration: () => {
        const duration = videoRef.current?.duration;
        return duration && Number.isFinite(duration) ? duration : null;
      },
      pause: () => videoRef.current?.pause(),
    }),
    [],
  );

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.autoplay = false;
    setError(null);

    const stopTracking = trackWatchEvents(video, (event) =>
      listenerRef.current?.(event),
    );

    let created: ShakaPlayer | null = null;
    let cancelled = false;
    void (async () => {
      // Shaka touches browser APIs at import time, so load it in the browser only.
      const { default: shaka } =
        await import("shaka-player/dist/shaka-player.dash");
      if (cancelled) return;
      shaka.polyfill.installAll();
      if (!shaka.Player.isBrowserSupported()) {
        setError("This browser can't play these videos.");
        return;
      }
      const instance = new shaka.Player();
      created = instance;
      instance.addEventListener("error", (event) => {
        setError(
          playerErrorMessage((event as Event & { detail?: unknown }).detail),
        );
      });
      try {
        await instance.attach(video);
        if (cancelled) return;
        await instance.load(manifestUrl(videoId), initialStartAt);
        if (!cancelled) setPlayer(instance);
      } catch (loadError) {
        if (!cancelled) setError(playerErrorMessage(loadError));
      }
    })();

    return () => {
      cancelled = true;
      stopTracking();
      setPlayer(null);
      void created?.destroy();
    };
  }, [videoId, initialStartAt]);

  const notices = (
    <>
      {error && (
        <p role="alert" className="text-destructive">
          {error}{" "}
          <button
            type="button"
            className="underline"
            onClick={() => window.location.reload()}
          >
            Reload
          </button>
        </p>
      )}
    </>
  );

  return (
    <>
      <div className="flex w-full justify-center bg-black">
        <div
          ref={containerRef}
          className="relative aspect-video max-h-[80vh] w-full overflow-hidden bg-black [&:fullscreen]:aspect-auto [&:fullscreen]:max-h-none"
        >
          <video
            ref={attachVideo}
            playsInline
            preload="metadata"
            poster={poster ?? undefined}
            className="size-full bg-black object-contain"
          />
          <PlayerControls
            videoId={videoId}
            media={media}
            player={player}
            containerRef={containerRef}
            chapters={chapters}
            segments={segments}
          >
            <SponsorSkip videoId={videoId} />
          </PlayerControls>
        </div>
      </div>
      {children ? children(notices) : notices}
    </>
  );
}

const NO_CHAPTERS: readonly Chapter[] = [];
const NO_SEGMENTS: readonly SponsorSegment[] = [];

/** A short explanation of a Shaka error (`shaka.util.Error`) or anything else. */
function playerErrorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null && "code" in error) {
    const { code, data } = error as { code: number; data?: unknown[] };
    // 1001 BAD_HTTP_STATUS: data is [uri, status, ...]
    const status = code === 1001 ? data?.[1] : undefined;
    if (status === 409) {
      return "This video changed on YouTube. Reload to keep watching.";
    }
    if (status === 404) return "This video can't be played.";
    if (status === 422)
      return "This video has no playable streams (is it live?).";
    return `The video couldn't be played (error ${code}).`;
  }
  return "The video couldn't be played.";
}
