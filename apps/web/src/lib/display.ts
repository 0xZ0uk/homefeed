/**
 * How feed items are shown. Thumbnails and view counts are off by default, in
 * keeping with the feed's design against compulsion; the user can turn them
 * on. The choice is a per-browser display preference stored in a cookie, so
 * the server renders the page the right way on the first load.
 */
export interface DisplayPrefs {
  thumbnails: boolean;
  viewCounts: boolean;
}

export const DISPLAY_COOKIE = "homefeed_display";

export const DEFAULT_DISPLAY: DisplayPrefs = {
  thumbnails: false,
  viewCounts: false,
};

/** Read prefs from the cookie value, falling back to defaults per field. */
export function parseDisplayPrefs(value: string | undefined): DisplayPrefs {
  if (!value) return DEFAULT_DISPLAY;
  try {
    const parsed: unknown = JSON.parse(value);
    return normalizeDisplayPrefs(parsed);
  } catch {
    return DEFAULT_DISPLAY;
  }
}

/** Keep only known boolean fields; anything else gets the default. */
export function normalizeDisplayPrefs(value: unknown): DisplayPrefs {
  const record =
    typeof value === "object" && value !== null
      ? (value as Record<string, unknown>)
      : {};
  return {
    thumbnails:
      typeof record.thumbnails === "boolean"
        ? record.thumbnails
        : DEFAULT_DISPLAY.thumbnails,
    viewCounts:
      typeof record.viewCounts === "boolean"
        ? record.viewCounts
        : DEFAULT_DISPLAY.viewCounts,
  };
}

export function serializeDisplayPrefs(prefs: DisplayPrefs): string {
  return JSON.stringify(normalizeDisplayPrefs(prefs));
}
