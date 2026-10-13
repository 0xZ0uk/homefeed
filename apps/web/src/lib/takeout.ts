/** Helpers for the Takeout import on the settings page. Pure, so they are easy to test. */

import type { ImportReport } from "@homefeed/api-client";

/** Largest upload accepted, matching the API's limit. */
export const MAX_TAKEOUT_BYTES = 256 * 1024 * 1024;
/** Default for "subscribe to channels watched at least this many times". */
export const DEFAULT_SUBSCRIBE_MIN_WATCHES = 5;

export interface TakeoutOptions {
  /** Subscribe to channels watched at least this often; null subscribes to none. */
  subscribeMinWatches: number | null;
}

/**
 * Read and check the upload form: the file and the subscribe option. Returns an
 * error message instead when something is off.
 */
export function parseTakeoutForm(
  form: FormData,
):
  | { ok: true; file: File; options: TakeoutOptions }
  | { ok: false; message: string } {
  const file = form.get("file");
  if (!(file instanceof File) || file.size === 0) {
    return {
      ok: false,
      message: "Choose your watch-history.json or .html file.",
    };
  }
  if (file.size > MAX_TAKEOUT_BYTES) {
    return { ok: false, message: "That file is too large (over 256 MB)." };
  }
  if (form.get("subscribe") !== "on") {
    return { ok: true, file, options: { subscribeMinWatches: null } };
  }
  const raw = form.get("subscribe_min_watches");
  const min = typeof raw === "string" ? Number(raw) : Number.NaN;
  if (!Number.isInteger(min) || min < 1) {
    return {
      ok: false,
      message:
        "The number of watches to subscribe at must be a whole number of at least 1.",
    };
  }
  return { ok: true, file, options: { subscribeMinWatches: min } };
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en")} ${n === 1 ? one : many}`;
}

/** What an import did, as short sentences for the result panel. */
export function summarizeImport(report: ImportReport): string[] {
  const lines = [
    `Imported ${plural(report.watches, "watch", "watches")} of ${plural(report.videos, "video")} from ${plural(report.channels, "channel")}.`,
    `Added ${plural(report.new_candidates, "video")} to your candidates and ${plural(report.new_channels, "new channel")}.`,
  ];
  if (report.subscribed.length > 0) {
    lines.push(`Subscribed to ${plural(report.subscribed.length, "channel")}.`);
  }
  const notImported = [
    report.removed > 0 &&
      `${plural(report.removed, "removed or private video")}`,
    report.malformed > 0 &&
      `${plural(report.malformed, "unreadable entry", "unreadable entries")}`,
    report.skipped > 0 &&
      `${plural(report.skipped, "other entry", "other entries")} (ads, searches)`,
  ].filter((part): part is string => Boolean(part));
  if (notImported.length > 0) {
    lines.push(`Not imported: ${notImported.join(", ")}.`);
  }
  return lines;
}
