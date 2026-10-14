import { useCallback, useRef, useSyncExternalStore } from "react";

/**
 * What the player's controls show about a `<video>` element, kept in step
 * with its media events.
 */

export type ShakaPlayer = InstanceType<
  (typeof import("shaka-player/dist/shaka-player.dash"))["default"]["Player"]
>;

export interface MediaState {
  paused: boolean;
  ended: boolean;
  /** Waiting for data while it should be playing. */
  waiting: boolean;
  currentTime: number;
  /** Seconds, or null until known. */
  duration: number | null;
  /** End of the buffered range around `currentTime`, in seconds. */
  bufferedEnd: number;
  volume: number;
  muted: boolean;
  playbackRate: number;
}

const EVENTS = [
  "play",
  "pause",
  "playing",
  "waiting",
  "canplay",
  "ended",
  "timeupdate",
  "durationchange",
  "loadedmetadata",
  "progress",
  "seeking",
  "seeked",
  "volumechange",
  "ratechange",
  "emptied",
] as const;

const INITIAL: MediaState = {
  paused: true,
  ended: false,
  waiting: false,
  currentTime: 0,
  duration: null,
  bufferedEnd: 0,
  volume: 1,
  muted: false,
  playbackRate: 1,
};

function bufferedEndAt(media: HTMLMediaElement): number {
  const { buffered, currentTime } = media;
  for (let i = 0; i < buffered.length; i++) {
    if (buffered.start(i) <= currentTime && currentTime <= buffered.end(i)) {
      return buffered.end(i);
    }
  }
  return currentTime;
}

function read(media: HTMLMediaElement, waiting: boolean): MediaState {
  const duration = media.duration;
  return {
    paused: media.paused,
    ended: media.ended,
    waiting: waiting && !media.paused,
    currentTime: Number.isFinite(media.currentTime) ? media.currentTime : 0,
    duration: Number.isFinite(duration) && duration > 0 ? duration : null,
    bufferedEnd: bufferedEndAt(media),
    volume: media.volume,
    muted: media.muted,
    playbackRate: media.playbackRate,
  };
}

function same(a: MediaState, b: MediaState): boolean {
  return (Object.keys(a) as (keyof MediaState)[]).every((k) => a[k] === b[k]);
}

/** `media`'s playback state (defaults while it's null), re-rendering on change. */
export function useMediaState(media: HTMLMediaElement | null): MediaState {
  const snapshot = useRef(INITIAL);
  const waiting = useRef(false);

  const subscribe = useCallback(
    (onChange: () => void) => {
      if (!media) return () => {};
      const update = (event?: Event) => {
        if (event?.type === "waiting" || event?.type === "seeking") {
          waiting.current = true;
        } else if (
          event?.type === "playing" ||
          event?.type === "canplay" ||
          event?.type === "seeked" ||
          event?.type === "pause"
        ) {
          waiting.current = false;
        }
        const next = read(media, waiting.current);
        if (!same(next, snapshot.current)) {
          snapshot.current = next;
          onChange();
        }
      };
      for (const type of EVENTS) media.addEventListener(type, update);
      update();
      return () => {
        for (const type of EVENTS) media.removeEventListener(type, update);
      };
    },
    [media],
  );

  return useSyncExternalStore(
    subscribe,
    () => (media ? snapshot.current : INITIAL),
    () => INITIAL,
  );
}
