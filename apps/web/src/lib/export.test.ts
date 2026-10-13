import { describe, expect, it } from "vitest";

import { DEFAULT_DISPLAY } from "./display";
import { exportFilename, withDisplayPrefs } from "./export";

describe("exportFilename", () => {
  it("uses the export's date", () => {
    expect(exportFilename("2026-10-13T09:30:00.000Z")).toBe(
      "homefeed-export-2026-10-13.json",
    );
  });

  it("falls back to an undated name", () => {
    expect(exportFilename("")).toBe("homefeed-export.json");
  });
});

describe("withDisplayPrefs", () => {
  it("adds the display settings next to the API's settings", () => {
    const display = { ...DEFAULT_DISPLAY, textOnly: true };
    const data = { ratings: [], settings: { stored: { a: 1 } } };

    expect(withDisplayPrefs(data, display)).toEqual({
      ratings: [],
      settings: { stored: { a: 1 }, display },
    });
  });

  it("creates the settings section when it is missing", () => {
    expect(withDisplayPrefs({}, DEFAULT_DISPLAY)).toEqual({
      settings: { display: DEFAULT_DISPLAY },
    });
  });
});
