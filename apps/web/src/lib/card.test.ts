import { describe, expect, it } from "vitest";

import {
  CLICKBAIT_SCORE,
  DEEP_DIVE_DEPTH,
  cardFlags,
  dismissedLabel,
  formatLength,
  progressPercent,
  ratedLabel,
} from "./card";

describe("cardFlags", () => {
  it("flags a deep dive from the depth threshold up", () => {
    expect(cardFlags({ depth: DEEP_DIVE_DEPTH, clickbait: 0 })).toEqual([
      "deep-dive",
    ]);
    expect(cardFlags({ depth: 0.69, clickbait: 0 })).toEqual([]);
    expect(cardFlags({ depth: 1, clickbait: 0 })).toEqual(["deep-dive"]);
  });

  it("flags likely clickbait from the clickbait threshold up", () => {
    expect(cardFlags({ depth: 0, clickbait: CLICKBAIT_SCORE })).toEqual([
      "clickbait",
    ]);
    expect(cardFlags({ depth: 0, clickbait: 0.59 })).toEqual([]);
  });

  it("can flag both, deep dive first", () => {
    expect(cardFlags({ depth: 0.9, clickbait: 0.8 })).toEqual([
      "deep-dive",
      "clickbait",
    ]);
  });

  it("flags nothing for a video the LLM hasn't seen", () => {
    expect(cardFlags(null)).toEqual([]);
    expect(cardFlags(undefined)).toEqual([]);
  });

  it("ignores rage-bait scores it isn't given", () => {
    const llm = { depth: 0.1, clickbait: 0.1, rage_bait: 1 };

    expect(cardFlags(llm)).toEqual([]);
  });
});

describe("formatLength", () => {
  it("says minutes under an hour", () => {
    expect(formatLength(360)).toBe("6 min");
    expect(formatLength(600)).toBe("10 min");
    expect(formatLength(59 * 60)).toBe("59 min");
  });

  it("says hours and minutes from an hour up", () => {
    expect(formatLength(4140)).toBe("1 h 9 min");
    expect(formatLength(3600)).toBe("1 h");
    expect(formatLength(7200)).toBe("2 h");
    expect(formatLength(5400)).toBe("1 h 30 min");
  });

  it("rounds to the nearest minute, carrying into the hour", () => {
    expect(formatLength(389)).toBe("6 min"); // 6:29
    expect(formatLength(390)).toBe("7 min"); // 6:30
    expect(formatLength(3570)).toBe("1 h"); // 59:30
    expect(formatLength(3599)).toBe("1 h");
  });

  it("says when it's under a minute", () => {
    expect(formatLength(0)).toBe("under 1 min");
    expect(formatLength(29)).toBe("under 1 min");
    expect(formatLength(30)).toBe("1 min");
  });

  it("is null when unknown", () => {
    expect(formatLength(null)).toBeNull();
    expect(formatLength(undefined)).toBeNull();
    expect(formatLength(-1)).toBeNull();
    expect(formatLength(Number.NaN)).toBeNull();
  });
});

describe("progressPercent", () => {
  it("rounds to a whole percentage", () => {
    expect(progressPercent(0.5)).toBe(50);
    expect(progressPercent(0.1234)).toBe(12);
    expect(progressPercent(1)).toBe(100);
  });

  it("keeps it in range", () => {
    expect(progressPercent(1.5)).toBe(100);
    expect(progressPercent(-0.2)).toBeNull();
  });

  it("is null when there is nothing to show", () => {
    expect(progressPercent(null)).toBeNull();
    expect(progressPercent(undefined)).toBeNull();
    expect(progressPercent(0)).toBeNull();
    expect(progressPercent(0.004)).toBeNull();
    expect(progressPercent(Number.NaN)).toBeNull();
  });
});

describe("dismissedLabel", () => {
  it("adds the reason when there is one", () => {
    expect(dismissedLabel("Clickbait")).toBe("Dismissed: Clickbait");
    expect(dismissedLabel("  Too long ")).toBe("Dismissed: Too long");
  });

  it("is just 'Dismissed' without a reason", () => {
    expect(dismissedLabel(null)).toBe("Dismissed");
    expect(dismissedLabel("   ")).toBe("Dismissed");
    expect(dismissedLabel(undefined)).toBe("Dismissed");
  });
});

describe("ratedLabel", () => {
  it("names the score", () => {
    expect(ratedLabel(8)).toBe("You rated it 8");
  });
});
