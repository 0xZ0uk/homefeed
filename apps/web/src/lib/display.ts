/**
 * How feed items are shown. Thumbnails and view counts are off by default, in
 * keeping with the feed's design against compulsion; the user can turn them
 * on. Text-only mode goes further and hides all imagery: feed thumbnails
 * (whatever their own toggle says), channel avatars and the player's poster.
 * The choices are per-browser display settings stored in a cookie, so the
 * server renders the page the right way on the first load.
 */
export interface DisplayPrefs {
  thumbnails: boolean;
  viewCounts: boolean;
  textOnly: boolean;
}

export const DISPLAY_COOKIE = "homefeed_display";

export const DEFAULT_DISPLAY: DisplayPrefs = {
  thumbnails: false,
  viewCounts: false,
  textOnly: false,
};

/** Whether images (thumbnails, avatars, posters) may be shown at all. */
export function showsImages(prefs: DisplayPrefs): boolean {
  return !prefs.textOnly;
}

/** Whether feed items show their thumbnails. */
export function showsThumbnails(prefs: DisplayPrefs): boolean {
  return prefs.thumbnails && showsImages(prefs);
}

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
  const flag = (key: keyof DisplayPrefs): boolean => {
    const field = record[key];
    return typeof field === "boolean" ? field : DEFAULT_DISPLAY[key];
  };
  return {
    thumbnails: flag("thumbnails"),
    viewCounts: flag("viewCounts"),
    textOnly: flag("textOnly"),
  };
}

export function serializeDisplayPrefs(prefs: DisplayPrefs): string {
  return JSON.stringify(normalizeDisplayPrefs(prefs));
}
