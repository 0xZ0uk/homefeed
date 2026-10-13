import type { ImportReport } from "@homefeed/api-client";
import { describe, expect, it } from "vitest";

import {
  MAX_TAKEOUT_BYTES,
  parseTakeoutForm,
  summarizeImport,
} from "./takeout";

function form(entries: Record<string, string | File>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.set(key, value);
  return data;
}

const FILE = new File(["[]"], "watch-history.json", {
  type: "application/json",
});

const REPORT: ImportReport = {
  format: "json",
  entries: 14,
  watches: 5,
  removed: 2,
  malformed: 5,
  skipped: 2,
  videos: 4,
  channels: 2,
  new_videos: 4,
  new_channels: 2,
  new_candidates: 4,
  subscribed: [],
  oldest_watch_at: "2026-09-01T08:00:00.000Z",
  newest_watch_at: "2026-10-10T20:15:02.123Z",
};

describe("parseTakeoutForm", () => {
  it("reads the file without subscribing by default", () => {
    expect(parseTakeoutForm(form({ file: FILE }))).toEqual({
      ok: true,
      file: FILE,
      options: { subscribeMinWatches: null },
    });
  });

  it("reads the subscribe threshold when subscribing is on", () => {
    const result = parseTakeoutForm(
      form({ file: FILE, subscribe: "on", subscribe_min_watches: "3" }),
    );
    expect(result).toMatchObject({
      ok: true,
      options: { subscribeMinWatches: 3 },
    });
  });

  it("ignores the threshold when subscribing is off", () => {
    const result = parseTakeoutForm(
      form({ file: FILE, subscribe_min_watches: "0" }),
    );
    expect(result).toMatchObject({
      ok: true,
      options: { subscribeMinWatches: null },
    });
  });

  it("rejects a missing, empty or oversized file", () => {
    expect(parseTakeoutForm(form({})).ok).toBe(false);
    expect(
      parseTakeoutForm(form({ file: new File([], "empty.json") })).ok,
    ).toBe(false);
    const huge = new File(["x"], "huge.json");
    Object.defineProperty(huge, "size", { value: MAX_TAKEOUT_BYTES + 1 });
    expect(parseTakeoutForm(form({ file: huge }))).toEqual({
      ok: false,
      message: "That file is too large (over 256 MB).",
    });
  });

  it("rejects a bad threshold", () => {
    for (const value of ["0", "-2", "1.5", "lots", ""]) {
      const result = parseTakeoutForm(
        form({ file: FILE, subscribe: "on", subscribe_min_watches: value }),
      );
      expect(result.ok).toBe(false);
    }
  });
});

describe("summarizeImport", () => {
  it("says what was imported and what wasn't", () => {
    expect(summarizeImport(REPORT)).toEqual([
      "Imported 5 watches of 4 videos from 2 channels.",
      "Added 4 videos to your candidates and 2 new channels.",
      "Not imported: 2 removed or private videos, 5 unreadable entries, 2 other entries (ads, searches).",
    ]);
  });

  it("mentions subscriptions and uses singulars", () => {
    expect(
      summarizeImport({
        ...REPORT,
        watches: 1,
        videos: 1,
        channels: 1,
        new_candidates: 1,
        new_channels: 1,
        removed: 1,
        malformed: 0,
        skipped: 0,
        subscribed: ["UCspaceexplained00000001"],
      }),
    ).toEqual([
      "Imported 1 watch of 1 video from 1 channel.",
      "Added 1 video to your candidates and 1 new channel.",
      "Subscribed to 1 channel.",
      "Not imported: 1 removed or private video.",
    ]);
  });

  it("leaves out the not-imported line when everything was imported", () => {
    expect(
      summarizeImport({ ...REPORT, removed: 0, malformed: 0, skipped: 0 }),
    ).toHaveLength(2);
  });
});
