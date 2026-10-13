import { describe, expect, it } from "vitest";

import {
  changedValues,
  minutesFromSeconds,
  parseOptionalMinutes,
  parseTime,
  parseWholeNumber,
  sourceLabel,
  timezoneItems,
} from "./settings";

describe("parseWholeNumber", () => {
  const limits = { min: 1, max: 200, label: "Videos per day" };

  it("reads whole numbers in range", () => {
    expect(parseWholeNumber(" 20 ", limits)).toEqual({ ok: true, value: 20 });
    expect(parseWholeNumber("1", limits)).toEqual({ ok: true, value: 1 });
  });

  it.each(["", "0", "201", "2.5", "lots"])("rejects %j", (raw) => {
    expect(parseWholeNumber(raw, limits)).toEqual({
      ok: false,
      message: "Videos per day must be a whole number from 1 to 200.",
    });
  });
});

describe("duration bounds in minutes", () => {
  it("turns minutes into seconds, and empty into no bound", () => {
    expect(parseOptionalMinutes("2", "Shortest video")).toEqual({
      ok: true,
      value: 120,
    });
    expect(parseOptionalMinutes("1.5", "Shortest video")).toEqual({
      ok: true,
      value: 90,
    });
    expect(parseOptionalMinutes("  ", "Shortest video")).toEqual({
      ok: true,
      value: null,
    });
  });

  it("rejects negative and unreadable values", () => {
    for (const raw of ["-1", "soon", "100000"]) {
      expect(parseOptionalMinutes(raw, "Longest video").ok).toBe(false);
    }
  });

  it("shows seconds as minutes", () => {
    expect(minutesFromSeconds(5400)).toBe("90");
    expect(minutesFromSeconds(90)).toBe("1.5");
    expect(minutesFromSeconds(null)).toBe("");
  });
});

describe("parseTime", () => {
  it("reads HH:MM, dropping seconds", () => {
    expect(parseTime("06:30", "the daily feed")).toEqual({
      ok: true,
      value: "06:30",
    });
    expect(parseTime("23:59:30", "training")).toEqual({
      ok: true,
      value: "23:59",
    });
  });

  it.each(["", "6:30", "24:00", "12:60", "noon"])("rejects %j", (raw) => {
    expect(parseTime(raw, "training")).toEqual({
      ok: false,
      message: "Choose a time for training.",
    });
  });
});

describe("timezoneItems", () => {
  it("puts the system default first, then the zones by name", () => {
    expect(
      timezoneItems(
        ["Europe/Lisbon", "America/New_York"],
        "Europe/Lisbon",
        null,
      ),
    ).toEqual([
      { value: "", label: "System default (Europe/Lisbon)" },
      { value: "America/New_York", label: "America/New York" },
      { value: "Europe/Lisbon", label: "Europe/Lisbon" },
    ]);
  });

  it("keeps the current zone even if the browser doesn't list it", () => {
    const items = timezoneItems(["UTC"], null, "Etc/GMT+1");

    expect(items[0]).toEqual({ value: "", label: "System default" });
    expect(items.map((item) => item.value)).toContain("Etc/GMT+1");
  });
});

describe("changedValues", () => {
  it("keeps only what differs, comparing lists and nulls by value", () => {
    expect(
      changedValues(
        {
          feed_size: 20,
          feed_max_duration_seconds: null,
          sponsorblock_categories: ["sponsor"],
          llm_model: "x",
        },
        {
          feed_size: 20,
          feed_max_duration_seconds: 600,
          sponsorblock_categories: ["sponsor"],
          llm_model: "y",
        },
      ),
    ).toEqual({ feed_max_duration_seconds: null, llm_model: "x" });
  });
});

describe("sourceLabel", () => {
  it("names where a value comes from", () => {
    expect(sourceLabel("user")).toBe("Changed here.");
    expect(sourceLabel("env")).toBe("From the server's configuration.");
    expect(sourceLabel("default")).toBe("");
    expect(sourceLabel(undefined)).toBe("");
  });
});
