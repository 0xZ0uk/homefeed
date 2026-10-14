import { describe, expect, it } from "vitest";

import { SCORES, isScore, scoreLabel, scoreText } from "./scores";

describe("isScore", () => {
  it("accepts the whole scores 1 to 10", () => {
    for (const value of SCORES) {
      expect(isScore(value)).toBe(true);
    }
    expect(SCORES).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  });

  it("rejects anything else", () => {
    for (const value of [0, 11, 4.2, 5.5, Number.NaN, "7", null, undefined]) {
      expect(isScore(value)).toBe(false);
    }
  });
});

describe("scoreLabel", () => {
  it("names every score", () => {
    expect(scoreLabel(1)).toBe("Awful");
    expect(scoreLabel(5)).toBe("Meh");
    expect(scoreLabel(10)).toBe("Amazing");
    expect(new Set(SCORES.map(scoreLabel)).size).toBe(10);
  });
});

describe("scoreText", () => {
  it("gives the word and the number", () => {
    expect(scoreText(8)).toBe("Great, 8 out of 10");
  });
});
