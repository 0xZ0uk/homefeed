/** Local playlists: input checks and labels. Pure, so server and client agree. */

export const PLAYLIST_NAME_MAX_LENGTH = 100;
export const PLAYLIST_DESCRIPTION_MAX_LENGTH = 1000;

/** `value` trimmed, or an error message when it can't be a playlist name. */
export function checkPlaylistName(
  value: unknown,
): { ok: true; name: string } | { ok: false; message: string } {
  if (typeof value !== "string" || !value.trim()) {
    return { ok: false, message: "Give the playlist a name." };
  }
  const name = value.trim();
  if (name.length > PLAYLIST_NAME_MAX_LENGTH) {
    return {
      ok: false,
      message: `Keep the name under ${PLAYLIST_NAME_MAX_LENGTH + 1} characters.`,
    };
  }
  return { ok: true, name };
}

/** `value` trimmed; throws when it isn't a string or is too long. */
export function checkPlaylistDescription(value: unknown): string {
  if (typeof value !== "string")
    throw new Error("description must be a string");
  const description = value.trim();
  if (description.length > PLAYLIST_DESCRIPTION_MAX_LENGTH) {
    throw new Error(
      `description must be at most ${PLAYLIST_DESCRIPTION_MAX_LENGTH} characters`,
    );
  }
  return description;
}

/** A positive integer id, or throws. */
export function checkPlaylistId(value: unknown): number {
  if (!Number.isInteger(value) || (value as number) < 1) {
    throw new Error("id must be a positive integer");
  }
  return value as number;
}

/** A 0-based position, or throws. */
export function checkPosition(value: unknown): number {
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new Error("position must be a non-negative integer");
  }
  return value as number;
}

/** "No videos", "1 video", "12 videos". */
export function describeItemCount(count: number): string {
  if (count === 0) return "No videos";
  return `${count} ${count === 1 ? "video" : "videos"}`;
}

/**
 * Where moving the item at `position` one step `direction` takes it, or null
 * when it is already at that end of a list of `length` items.
 */
export function stepPosition(
  position: number,
  direction: "up" | "down",
  length: number,
): number | null {
  const target = direction === "up" ? position - 1 : position + 1;
  return target < 0 || target >= length ? null : target;
}

/** `items` with the one at `from` moved to `to` (for optimistic updates). */
export function moveItem<T>(
  items: readonly T[],
  from: number,
  to: number,
): T[] {
  const result = [...items];
  if (from < 0 || from >= result.length) return result;
  const [moved] = result.splice(from, 1) as [T];
  result.splice(Math.min(Math.max(to, 0), result.length), 0, moved);
  return result;
}

/** A playlist id from a URL segment, or null when it isn't one. */
export function parsePlaylistId(value: string): number | null {
  if (!/^[1-9]\d{0,15}$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}
