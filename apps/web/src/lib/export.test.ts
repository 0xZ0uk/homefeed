import { describe, expect, it } from "vitest";

import { exportFilename } from "./export";

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
