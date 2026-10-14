import { describe, expect, it } from "vitest";

import {
  TAG_FILTERS,
  clampWeight,
  formatWeight,
  mutedTags,
  subscribedTags,
  tagState,
  tagWeights,
  weightEffect,
} from "./tag-subscriptions";

const sub = (slug: string, label: string, weight: number) => ({
  slug,
  label,
  weight,
});

describe("tagWeights", () => {
  it("maps subscriptions with a non-zero weight by slug", () => {
    const weights = tagWeights([
      sub("rust", "Rust", 0.5),
      sub("cooking", "Cooking", -0.5),
      sub("zero", "Zero", 0),
      sub("tiny", "Tiny", 0.001),
    ]);
    expect([...weights]).toEqual([
      ["rust", 0.5],
      ["cooking", -0.5],
    ]);
  });
});

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

describe("subscribedTags", () => {
  it("lists tags with a positive weight, alphabetically", () => {
    expect(
      subscribedTags([
        sub("rust", "Rust", 0.5),
        sub("go", "Go", 0),
        sub("drama", "Drama", -0.5),
        sub("ai", "AI", 0.1),
      ]),
    ).toEqual([
      { slug: "ai", label: "AI" },
      { slug: "rust", label: "Rust" },
    ]);
  });
});

describe("mutedTags", () => {
  it("lists tags with a negative weight, alphabetically", () => {
    expect(
      mutedTags([
        sub("rust", "Rust", -0.5),
        sub("go", "Go", 0),
        sub("ai", "AI", 0.5),
        sub("drama", "Drama", -0.1),
      ]),
    ).toEqual([
      { slug: "drama", label: "Drama" },
      { slug: "rust", label: "Rust" },
    ]);
  });
});

describe("tagState", () => {
  it("is subscribed at zero or more, muted below zero", () => {
    expect(tagState(undefined)).toBe("none");
    expect(tagState({ weight: 0.5 })).toBe("subscribed");
    expect(tagState({ weight: 0 })).toBe("subscribed");
    expect(tagState({ weight: -0.5 })).toBe("muted");
  });
});

describe("TAG_FILTERS", () => {
  it("offers all, subscribed and muted tags", () => {
    expect(TAG_FILTERS.map((f) => f.label)).toEqual([
      "All",
      "Subscribed",
      "Muted",
    ]);
  });
});
