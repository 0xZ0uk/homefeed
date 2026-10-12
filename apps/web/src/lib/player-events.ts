/**
 * Watch events from a `<video>` element, in one shape, for anything that needs
 * to know how a video was watched: the post-video rating prompt and watch
 * history (#15) subscribe through `VideoPlayer`'s `onWatchEvent`.
 *
 * - `play` / `pause` / `seeked`: the user (or the browser) changed playback.
 * - `ended`: playback reached the end. Nothing plays next.
 * - `close`: the viewer left: navigated away, closed the tab, or the page was
 *   hidden for good (`pagehide`). Sent once, and not after `ended` unless
 *   playback restarted.
 */

export type WatchEventType = "play" | "pause" | "seeked" | "ended" | "close";

export interface WatchEvent {
  type: WatchEventType;
  /** Playback position in seconds when the event happened. */
  position: number;
  /** Duration in seconds, or null while unknown. */
  duration: number | null;
}

export type WatchEventListener = (event: WatchEvent) => void;

/** The parts of a `<video>` element this needs (so tests can fake it). */
export interface MediaLike extends EventTarget {
  currentTime: number;
  duration: number;
}

/** The parts of `window` this needs. */
export type PageLike = Pick<
  EventTarget,
  "addEventListener" | "removeEventListener"
>;

const MEDIA_EVENTS = ["play", "pause", "seeked", "ended"] as const;

export function watchPosition(media: MediaLike): WatchEvent["position"] {
  return Number.isFinite(media.currentTime) ? media.currentTime : 0;
}

function watchDuration(media: MediaLike): WatchEvent["duration"] {
  return Number.isFinite(media.duration) && media.duration > 0
    ? media.duration
    : null;
}

/**
 * Report `media`'s watch events to `listener` until the returned function is
 * called. Calling it counts as the viewer leaving (`close`), as does the page
 * being unloaded.
 */
export function trackWatchEvents(
  media: MediaLike,
  listener: WatchEventListener,
  page: PageLike | null = typeof window === "undefined" ? null : window,
): () => void {
  let closed = false;
  let ended = false;

  const emit = (type: WatchEventType) => {
    listener({
      type,
      position: watchPosition(media),
      duration: watchDuration(media),
    });
  };

  const onMediaEvent = (event: Event) => {
    const type = event.type as (typeof MEDIA_EVENTS)[number];
    // A `pause` always precedes `ended`; it isn't a separate decision to stop.
    if (type === "pause" && isAtEnd(media)) return;
    if (type === "ended") ended = true;
    else if (type === "play") ended = false;
    emit(type);
  };

  const close = () => {
    if (closed) return;
    closed = true;
    if (!ended) emit("close");
  };

  for (const type of MEDIA_EVENTS) media.addEventListener(type, onMediaEvent);
  page?.addEventListener("pagehide", close);

  return () => {
    close();
    for (const type of MEDIA_EVENTS) {
      media.removeEventListener(type, onMediaEvent);
    }
    page?.removeEventListener("pagehide", close);
  };
}

function isAtEnd(media: MediaLike): boolean {
  const duration = watchDuration(media);
  return duration !== null && watchPosition(media) >= duration - 0.05;
}
