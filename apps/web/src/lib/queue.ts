import { isVideoId } from "#/lib/ids";

/** Pure helpers for the watch queue: optimistic updates and pasted links. */

interface Queued {
  id: number;
  video_id: string;
  position: number;
}

function renumbered<T extends Queued>(items: T[]): T[] {
  return items.map((item, position) =>
    item.position === position ? item : { ...item, position },
  );
}

/**
 * The queue with item `id` moved to `position` (clamped to the queue) and
 * positions renumbered, as the API will have it after the move.
 */
export function withItemMoved<T extends Queued>(
  items: T[],
  id: number,
  position: number,
): T[] {
  const moved = items.find((item) => item.id === id);
  if (!moved) return items;
  const rest = items.filter((item) => item !== moved);
  const to = Math.max(0, Math.min(position, rest.length));
  return renumbered([...rest.slice(0, to), moved, ...rest.slice(to)]);
}

/** The queue without item `id`, positions renumbered. */
export function withoutItem<T extends Queued>(items: T[], id: number): T[] {
  return renumbered(items.filter((item) => item.id !== id));
}

/**
 * What to watch after `videoId`: the item after it when it's queued, else the
 * first item. Null when nothing else is queued.
 */
export function nextInQueue<T extends Queued>(
  items: T[],
  videoId: string,
): T | null {
  const index = items.findIndex((item) => item.video_id === videoId);
  if (index === -1) return items[0] ?? null;
  return items[index + 1] ?? null;
}

const YOUTUBE_HOSTS = new Set([
  "youtube.com",
  "www.youtube.com",
  "m.youtube.com",
  "music.youtube.com",
  "youtube-nocookie.com",
  "www.youtube-nocookie.com",
]);

/**
 * The video id in a pasted video id or YouTube video link (watch, youtu.be,
 * shorts, live and embed links), or null when there isn't one.
 */
export function parseVideoInput(input: string): string | null {
  const value = input.trim();
  if (isVideoId(value)) return value;
  let url: URL;
  try {
    url = new URL(
      /^[a-z][a-z0-9+.-]*:\/\//i.test(value) ? value : `https://${value}`,
    );
  } catch {
    return null;
  }
  const host = url.hostname.toLowerCase();
  const segments = url.pathname.split("/").filter(Boolean);
  let id: string | null | undefined;
  if (host === "youtu.be") {
    id = segments[0];
  } else if (YOUTUBE_HOSTS.has(host)) {
    if (segments[0] === "watch") id = url.searchParams.get("v");
    else if (["shorts", "live", "embed", "v"].includes(segments[0] ?? "")) {
      id = segments[1];
    }
  }
  return id && isVideoId(id) ? id : null;
}
