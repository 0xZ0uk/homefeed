import { describe, expect, it } from "vitest";

import { PRIOR_LABELS, muteState, trialDaysLeft, trialLabel } from "./channels";

const now = new Date("2026-10-12T06:00:00.000Z");

describe("PRIOR_LABELS", () => {
  it("words the API's prior as a preference", () => {
    expect(PRIOR_LABELS).toEqual({
      love: "Love",
      like: "Like",
      neutral: "Neutral",
      skeptical: "Skeptical",
    });
  });
});

describe("muteState", () => {
  it("is off without a mute", () => {
    expect(muteState({ muted: false, muted_until: null }, now)).toEqual({
      kind: "off",
    });
  });

  it("is forever for a mute for good, whatever else is set", () => {
    expect(muteState({ muted: true, muted_until: null }, now)).toEqual({
      kind: "forever",
    });
    expect(
      muteState({ muted: true, muted_until: "2026-11-11T06:00:00.000Z" }, now),
    ).toEqual({ kind: "forever" });
  });

  it("is until a time that is ahead, and off once it has passed", () => {
    const until = "2026-11-11T06:00:00.000Z";
    expect(muteState({ muted: false, muted_until: until }, now)).toEqual({
      kind: "until",
      until,
    });
    expect(
      muteState({ muted: false, muted_until: until }, new Date(until)),
    ).toEqual({ kind: "off" });
    expect(
      muteState(
        { muted: false, muted_until: until },
        new Date("2026-12-01T00:00:00Z"),
      ),
    ).toEqual({ kind: "off" });
  });
});

describe("trialDaysLeft", () => {
  it("counts a started day as a day", () => {
    expect(trialDaysLeft("2026-10-26T06:00:00.000Z", now)).toBe(14);
    expect(trialDaysLeft("2026-10-26T05:00:00.000Z", now)).toBe(14);
    expect(trialDaysLeft("2026-10-13T06:00:00.000Z", now)).toBe(1);
    expect(trialDaysLeft("2026-10-12T06:00:01.000Z", now)).toBe(1);
  });

  it("is 0 once the trial is over or the time is unreadable", () => {
    expect(trialDaysLeft("2026-10-12T06:00:00.000Z", now)).toBe(0);
    expect(trialDaysLeft("2026-10-01T00:00:00.000Z", now)).toBe(0);
    expect(trialDaysLeft("soon", now)).toBe(0);
  });
});

describe("trialLabel", () => {
  it("says how many days are left", () => {
    expect(trialLabel("2026-10-21T06:00:00.000Z", now)).toBe(
      "Trial · 9 days left",
    );
    expect(trialLabel("2026-10-13T00:00:00.000Z", now)).toBe(
      "Trial · 1 day left",
    );
  });

  it("says when it is over but not yet settled", () => {
    expect(trialLabel("2026-10-12T05:00:00.000Z", now)).toBe("Trial · ended");
  });

  it("is null without a trial", () => {
    expect(trialLabel(null, now)).toBeNull();
    expect(trialLabel(undefined, now)).toBeNull();
  });
});
