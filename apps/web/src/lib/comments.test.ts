import { describe, expect, it } from "vitest";

import { formatLikes } from "./comments";

describe("formatLikes", () => {
  it("formats counts compactly", () => {
    expect(formatLikes(1)).toBe("1 like");
    expect(formatLikes(1234)).toBe("1.2K likes");
    expect(formatLikes(4_800_000)).toBe("4.8M likes");
  });

  it("is null when unknown or zero", () => {
    expect(formatLikes(null)).toBeNull();
    expect(formatLikes(0)).toBeNull();
  });
});
