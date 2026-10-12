import { describe, expect, it } from "vitest";

import {
  DEFAULT_DISPLAY,
  normalizeDisplayPrefs,
  parseDisplayPrefs,
  serializeDisplayPrefs,
  showsImages,
  showsThumbnails,
} from "./display";

describe("display prefs", () => {
  it("defaults to a text-first feed", () => {
    expect(DEFAULT_DISPLAY).toEqual({
      thumbnails: false,
      viewCounts: false,
      textOnly: false,
    });
    expect(parseDisplayPrefs(undefined)).toEqual(DEFAULT_DISPLAY);
  });

  it("round-trips through the cookie value", () => {
    const prefs = { thumbnails: true, viewCounts: false, textOnly: true };
    expect(parseDisplayPrefs(serializeDisplayPrefs(prefs))).toEqual(prefs);
  });

  it("ignores malformed values", () => {
    expect(parseDisplayPrefs("not json")).toEqual(DEFAULT_DISPLAY);
    expect(parseDisplayPrefs("null")).toEqual(DEFAULT_DISPLAY);
    expect(parseDisplayPrefs('{"thumbnails":"yes","viewCounts":true}')).toEqual(
      { thumbnails: false, viewCounts: true, textOnly: false },
    );
  });

  it("drops unknown fields", () => {
    expect(
      normalizeDisplayPrefs({ thumbnails: true, viewCounts: true, extra: 1 }),
    ).toEqual({ thumbnails: true, viewCounts: true, textOnly: false });
  });

  it("reads cookies saved before text-only mode existed", () => {
    expect(parseDisplayPrefs('{"thumbnails":true,"viewCounts":true}')).toEqual({
      thumbnails: true,
      viewCounts: true,
      textOnly: false,
    });
  });

  it("hides every image in text-only mode", () => {
    const withThumbnails = { ...DEFAULT_DISPLAY, thumbnails: true };
    expect(showsImages(withThumbnails)).toBe(true);
    expect(showsThumbnails(withThumbnails)).toBe(true);
    const textOnly = { ...withThumbnails, textOnly: true };
    expect(showsImages(textOnly)).toBe(false);
    expect(showsThumbnails(textOnly)).toBe(false);
  });
});
