import { recordWatchEvent, type WatchEventInput } from "@homefeed/api-client";

import { isVideoId } from "#/lib/ids";
import { apiClient } from "#/server/api";

/**
 * `POST /watch-events` in this app: the player's beacons (see
 * `lib/watch-reporter.ts`) land here and are forwarded to the internal API.
 * Beacons can't carry a CSRF token, so cross-site requests are refused by
 * their `Sec-Fetch-Site` / `Origin` headers instead (the session cookie is
 * `SameSite=Lax`, which already keeps it off cross-site POSTs).
 */

const EVENT_TYPES: readonly WatchEventInput["event_type"][] = [
  "play",
  "pause",
  "seeked",
  "ended",
  "close",
];

/** Generous upper bound on positions and durations (about 115 days). */
const MAX_SECONDS = 1e7;

function isSeconds(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= MAX_SECONDS
  );
}

/** The event in a request body, or null if it isn't a valid one. */
export function parseWatchEvent(body: unknown): WatchEventInput | null {
  if (typeof body !== "object" || body === null) return null;
  const { video_id, event_type, position, duration } = body as Record<
    string,
    unknown
  >;
  if (typeof video_id !== "string" || !isVideoId(video_id)) return null;
  if (!EVENT_TYPES.includes(event_type as WatchEventInput["event_type"])) {
    return null;
  }
  if (!isSeconds(position)) return null;
  if (duration != null && !(isSeconds(duration) && duration > 0)) return null;
  return {
    video_id,
    event_type: event_type as WatchEventInput["event_type"],
    position,
    duration: duration ?? null,
  };
}

/** Whether the request came from this app's own pages. */
export function isSameOrigin(request: Request): boolean {
  const site = request.headers.get("sec-fetch-site");
  if (site !== null) return site === "same-origin";
  const origin = request.headers.get("origin");
  return origin === null || origin === new URL(request.url).origin;
}

type Record_ = (event: WatchEventInput) => Promise<boolean>;

async function recordWithApi(event: WatchEventInput): Promise<boolean> {
  const { response } = await recordWatchEvent({
    client: apiClient(),
    body: event,
  });
  return response?.ok ?? false;
}

/** Handle a `POST /watch-events` request. `record` is the seam for tests. */
export async function handleWatchEvent(
  request: Request,
  record: Record_ = recordWithApi,
): Promise<Response> {
  if (!isSameOrigin(request)) {
    return new Response("Forbidden", { status: 403 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return new Response("Invalid JSON", { status: 400 });
  }
  const event = parseWatchEvent(body);
  if (!event) return new Response("Invalid watch event", { status: 400 });
  try {
    if (!(await record(event))) {
      return new Response("The API refused the event", { status: 502 });
    }
  } catch {
    return new Response("The API could not be reached", { status: 502 });
  }
  return new Response(null, { status: 204 });
}
