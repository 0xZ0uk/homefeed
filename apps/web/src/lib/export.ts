/**
 * Helpers for the data export download on the settings page. Pure, so they
 * are easy to test.
 */

/** Where the settings page's download link points (see `routes/export[.]json.ts`). */
export const EXPORT_PATH = "/export.json";

/** The download's file name for an export taken at `exportedAt` (ISO 8601). */
export function exportFilename(exportedAt: string): string {
  const date = /^\d{4}-\d{2}-\d{2}/.exec(exportedAt)?.[0];
  return date ? `homefeed-export-${date}.json` : "homefeed-export.json";
}
