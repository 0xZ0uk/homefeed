import type { ScoreBreakdownOut } from "@homefeed/api-client";
import { describe, expect, it } from "vitest";

import { breakdownTerms, formatScore } from "./breakdown";

const rulesOnly: ScoreBreakdownOut = {
  model: 0,
  alpha: 0,
  channel: 0.8,
  similarity: 0,
  tags: {},
  final: 0.8,
  similarity_features: null,
};

describe("breakdownTerms", () => {
  it("lists channel, similarity and model for a rules-only score", () => {
    expect(breakdownTerms(rulesOnly)).toEqual([
      { key: "channel", label: "Channel", value: 0.8 },
      {
        key: "similarity",
        label: "Similarity to your ratings",
        value: 0,
        detail: "Not analyzed yet",
      },
      {
        key: "model",
        label: "Model",
        value: 0,
        detail: "No trained model yet",
      },
    ]);
  });

  it("adds a row per tag and the blended model term", () => {
    const terms = breakdownTerms({
      ...rulesOnly,
      model: 0.5,
      alpha: 0.2,
      tags: { woodworking: 0.4, drama: -0.3 },
      similarity: 0.25,
      similarity_features: {
        top_tier: { max: 0.912, mean: 0.4, nearest_video_id: "abcdefghijk" },
        bottom_tier: null,
      },
    });

    expect(terms.map((term) => [term.key, term.value])).toEqual([
      ["channel", 0.8],
      ["similarity", 0.25],
      ["tag:drama", -0.3],
      ["tag:woodworking", 0.4],
      ["model", 0.1],
    ]);
    expect(terms[1]?.detail).toBe(
      "Cosine similarity: closest top-tier video 0.91",
    );
    expect(terms[3]?.label).toBe("Tag “woodworking”");
    expect(terms[4]?.detail).toBe("+0.50 at weight 0.20");
  });

  it("sums to the final score", () => {
    const breakdown = {
      ...rulesOnly,
      model: -0.5,
      alpha: 0.4,
      similarity: 0.1,
      tags: { a: 0.2 },
      final: 0.8 - 0.2 + 0.1 + 0.2,
    };
    const sum = breakdownTerms(breakdown).reduce(
      (total, term) => total + term.value,
      0,
    );
    expect(sum).toBeCloseTo(breakdown.final);
  });
});

describe("formatScore", () => {
  it("signs non-zero scores", () => {
    expect(formatScore(0.254)).toBe("+0.25");
    expect(formatScore(-0.1)).toBe("-0.10");
    expect(formatScore(0)).toBe("0.00");
    expect(formatScore(-0.001)).toBe("0.00");
  });
});
