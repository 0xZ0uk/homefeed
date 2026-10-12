import type { WatchEvent } from "#/lib/player-events";

/**
 * Sending the player's watch events to `POST /watch-events` (this app's server
 * route, which forwards them to the API).
 *
 * Only discrete events are sent (play, pause, seeked, ended, close), never
 * `timeupdate`. Scrubbing fires a `seeked` per step, so seeks are debounced:
 * only the last one of a burst is sent, once the scrubbing has been quiet for
 * `seekQuietMs` or just before the next other event. Everything goes out with
 * `navigator.sendBeacon` (falling back to a keepalive `fetch`), so the `close`
 * sent while the page unloads still arrives.
 */

export const WATCH_EVENTS_PATH = "/watch-events";

/** The body of `POST /watch-events` (the API's `WatchEventInput`). */
export interface WatchEventPayload {
  video_id: string;
  event_type: WatchEvent["type"];
  position: number;
  duration: number | null;
}

export type SendWatchEvent = (payload: WatchEventPayload) => void;

export interface WatchEventReporter {
  report: (event: WatchEvent) => void;
  /** Send a debounced seek now, if one is waiting. */
  flush: () => void;
}

/** Positions to a tenth of a second; that's plenty for history and resume. */
function round(seconds: number): number {
  return Math.max(0, Math.round(seconds * 10) / 10);
}

export function toPayload(
  videoId: string,
  event: WatchEvent,
): WatchEventPayload {
  return {
    video_id: videoId,
    event_type: event.type,
    position: round(event.position),
    duration:
      event.duration != null && event.duration > 0
        ? round(event.duration)
        : null,
  };
}

export function createWatchEventReporter(
  videoId: string,
  send: SendWatchEvent,
  { seekQuietMs = 2000 }: { seekQuietMs?: number } = {},
): WatchEventReporter {
  let pendingSeek: WatchEventPayload | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const flush = () => {
    clearTimeout(timer);
    timer = undefined;
    if (pendingSeek) {
      const seek = pendingSeek;
      pendingSeek = null;
      send(seek);
    }
  };

  return {
    report(event) {
      const payload = toPayload(videoId, event);
      if (event.type === "seeked") {
        pendingSeek = payload;
        clearTimeout(timer);
        timer = setTimeout(flush, seekQuietMs);
        return;
      }
      flush();
      send(payload);
    },
    flush,
  };
}

/** The parts of the browser this needs (so tests can fake them). */
export interface BeaconEnv {
  sendBeacon?: (url: string, data: Blob) => boolean;
  fetch: typeof fetch;
}

/**
 * Send one event without waiting for (or caring about) the answer: as a beacon,
 * or a keepalive `fetch` when beacons aren't available or the queue is full.
 */
export function sendWatchEvent(
  payload: WatchEventPayload,
  env: BeaconEnv = {
    sendBeacon:
      typeof navigator !== "undefined" && "sendBeacon" in navigator
        ? navigator.sendBeacon.bind(navigator)
        : undefined,
    fetch: globalThis.fetch.bind(globalThis),
  },
): void {
  const body = JSON.stringify(payload);
  const blob = new Blob([body], { type: "application/json" });
  if (env.sendBeacon?.(WATCH_EVENTS_PATH, blob)) return;
  void env
    .fetch(WATCH_EVENTS_PATH, {
      method: "POST",
      body,
      headers: { "content-type": "application/json" },
      keepalive: true,
      credentials: "same-origin",
    })
    .catch(() => {
      // Watch history is best effort; a lost event isn't worth bothering anyone.
    });
}
