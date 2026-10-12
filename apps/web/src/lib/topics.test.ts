import { describe, expect, it } from "vitest";

import { clampWeight, decayNote, formatWeight, weightEffect } from "./topics";

describe("clampWeight", () => {
  it("rounds to the slider step", () => {
    expect(clampWeight(0.149)).toBe(0.15);
    expect(clampWeight(0.1 + 0.05)).toBe(0.15);
    expect(clampWeight(-0.62)).toBe(-0.6);
  });

  it("clamps to [-1, 1] and avoids negative zero", () => {
    expect(clampWeight(3)).toBe(1);
    expect(clampWeight(-1.2)).toBe(-1);
    expect(Object.is(clampWeight(-0.01), 0)).toBe(true);
    expect(clampWeight(Number.NaN)).toBe(0);
  });
});

describe("formatWeight", () => {
  it("shows the sign", () => {
    expect(formatWeight(0.5)).toBe("+0.50");
    expect(formatWeight(-0.25)).toBe("−0.25");
    expect(formatWeight(0)).toBe("0.00");
    expect(formatWeight(-0.001)).toBe("0.00");
  });
});

describe("weightEffect", () => {
  it("names the effect", () => {
    expect(weightEffect(0.3)).toBe("Boost");
    expect(weightEffect(-1)).toBe("Suppress");
    expect(weightEffect(0)).toBe("No effect");
  });
});

describe("decayNote", () => {
  const now = new Date("2026-10-12T12:00:00Z");

  it("shows the current weight and the last reaffirmation", () => {
    expect(
      decayNote(
        { effective_weight: 0.4, reaffirmed_at: "2026-09-12T12:00:00Z" },
        now,
      ),
    ).toBe("Now +0.40, reaffirmed 1 month ago");
  });

  it("leaves out an unknown date", () => {
    expect(decayNote({ effective_weight: -1, reaffirmed_at: "" }, now)).toBe(
      "Now −1.00",
    );
  });
});
