import {
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type ReactNode,
  type Ref,
} from "react";

import { ResumeNotice } from "#/components/ResumeNotice";
import { useRegisterPlayerMedia } from "#/components/PlayerMedia";
import {
  trackWatchEvents,
  watchPosition,
  type WatchEventListener,
} from "#/lib/player-events";
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
  /** Play, pause, seek, end and close (leaving the page), with the position. */
  onWatchEvent?: WatchEventListener;
  ref?: Ref<VideoPlayerHandle>;
  /** Lays out what follows the player band; gets the resume notice and error
   * message to place inside the padded content area. */
  children?: (notices: ReactNode) => ReactNode;
}

type ShakaPlayer = InstanceType<
  (typeof import("shaka-player/dist/shaka-player.dash"))["default"]["Player"]
>;

/**
 * Shaka Player over the video's DASH manifest, proxied through this app.
 *
 * Playback only starts when the viewer presses play (no autoplay), and when the
 * video ends nothing else is offered or played.
 */
export function VideoPlayer({
  videoId,
  poster,
  startAt,
  onWatchEvent,
  ref,
  children,
}: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
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

    let player: ShakaPlayer | null = null;
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
      player = instance;
      instance.addEventListener("error", (event) => {
        setError(
          playerErrorMessage((event as Event & { detail?: unknown }).detail),
        );
      });
      try {
        await instance.attach(video);
        if (cancelled) return;
        await instance.load(manifestUrl(videoId), initialStartAt);
      } catch (loadError) {
        if (!cancelled) setError(playerErrorMessage(loadError));
      }
    })();

    return () => {
      cancelled = true;
      stopTracking();
      void player?.destroy();
    };
  }, [videoId, initialStartAt]);

  const notices = (
    <>
      <ResumeNotice startAt={initialStartAt} videoRef={videoRef} />
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
        <video
          ref={videoRef}
          controls
          playsInline
          preload="metadata"
          poster={poster ?? undefined}
          className="aspect-video h-auto max-h-[calc(100svh-3.5rem)] w-full bg-black"
        />
      </div>
      {children ? children(notices) : notices}
    </>
  );
}

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
