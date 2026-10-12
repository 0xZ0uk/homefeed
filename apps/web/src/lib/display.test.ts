import { describe, expect, it } from "vitest";

import {
  DEFAULT_DISPLAY,
  normalizeDisplayPrefs,
  parseDisplayPrefs,
  serializeDisplayPrefs,
} from "./display";

describe("display prefs", () => {
  it("defaults to a text-first feed", () => {
    expect(DEFAULT_DISPLAY).toEqual({ thumbnails: false, viewCounts: false });
    expect(parseDisplayPrefs(undefined)).toEqual(DEFAULT_DISPLAY);
  });

  it("round-trips through the cookie value", () => {
    const prefs = { thumbnails: true, viewCounts: false };
    expect(parseDisplayPrefs(serializeDisplayPrefs(prefs))).toEqual(prefs);
  });

  it("ignores malformed values", () => {
    expect(parseDisplayPrefs("not json")).toEqual(DEFAULT_DISPLAY);
    expect(parseDisplayPrefs("null")).toEqual(DEFAULT_DISPLAY);
    expect(parseDisplayPrefs('{"thumbnails":"yes","viewCounts":true}')).toEqual(
      { thumbnails: false, viewCounts: true },
    );
  });

  it("drops unknown fields", () => {
    expect(
      normalizeDisplayPrefs({ thumbnails: true, viewCounts: true, extra: 1 }),
    ).toEqual({ thumbnails: true, viewCounts: true });
  });
});
