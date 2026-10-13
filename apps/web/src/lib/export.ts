/**
 * Helpers for the data export download on the settings page. Pure, so they
 * are easy to test.
 */

import type { DisplayPrefs } from "#/lib/display";

/** Where the settings page's download link points (see `routes/export[.]json.ts`). */
export const EXPORT_PATH = "/export.json";

/** The download's file name for an export taken at `exportedAt` (ISO 8601). */
export function exportFilename(exportedAt: string): string {
  const date = /^\d{4}-\d{2}-\d{2}/.exec(exportedAt)?.[0];
  return date ? `homefeed-export-${date}.json` : "homefeed-export.json";
}

/**
 * Add this browser's display settings (kept in a cookie by the web app, so the
 * API can't see them) to the API's export, under `settings.display`.
 */
export function withDisplayPrefs(
  data: Record<string, unknown>,
  display: DisplayPrefs,
): Record<string, unknown> {
  const settings = data.settings;
  const existing =
    typeof settings === "object" &&
    settings !== null &&
    !Array.isArray(settings)
      ? (settings as Record<string, unknown>)
      : {};
  return { ...data, settings: { ...existing, display } };
}
