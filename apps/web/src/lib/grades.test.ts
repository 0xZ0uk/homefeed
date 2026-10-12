import { describe, expect, it } from "vitest";

import {
  MODIFIERS,
  TIERS,
  composeGrade,
  isGrade,
  splitGrade,
  type Modifier,
} from "./grades";

const ALL_MODIFIERS: Modifier[] = ["", ...MODIFIERS];

describe("composeGrade", () => {
  it("is the plain tier without a modifier", () => {
    expect(composeGrade("B")).toBe("B");
    expect(composeGrade("S", "")).toBe("S");
  });

  it("appends the modifier", () => {
    expect(composeGrade("A", "+")).toBe("A+");
    expect(composeGrade("F", "--")).toBe("F--");
  });

  it("makes the 30 grades", () => {
    const grades = TIERS.flatMap((tier) =>
      ALL_MODIFIERS.map((modifier) => composeGrade(tier, modifier)),
    );
    expect(new Set(grades).size).toBe(30);
    expect(grades.every(isGrade)).toBe(true);
  });
});

describe("splitGrade", () => {
  it("round-trips every grade", () => {
    for (const tier of TIERS) {
      for (const modifier of ALL_MODIFIERS) {
        expect(splitGrade(composeGrade(tier, modifier))).toEqual({
          tier,
          modifier,
        });
      }
    }
  });

  it("rejects anything else", () => {
    for (const value of ["", "b", "E", "B+++", "B+-", "+", "BB", " B"]) {
      expect(splitGrade(value)).toBeNull();
      expect(isGrade(value)).toBe(false);
    }
    expect(isGrade(undefined)).toBe(false);
  });
});
