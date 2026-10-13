import { describe, expect, it } from "vitest";

import { formatScore, isScore } from "./scores";

describe("isScore", () => {
  it("accepts 1 to 10 with one decimal", () => {
    for (const value of [1, 4.2, 6.7, 9.9, 10]) {
      expect(isScore(value)).toBe(true);
    }
  });

  it("rejects anything else", () => {
    for (const value of [0.9, 10.1, 4.25, Number.NaN, "7", null, undefined]) {
      expect(isScore(value)).toBe(false);
    }
  });
});

describe("formatScore", () => {
  it("always shows one decimal", () => {
    expect(formatScore(7)).toBe("7.0");
    expect(formatScore(9.9)).toBe("9.9");
    expect(formatScore(10)).toBe("10.0");
  });
});
