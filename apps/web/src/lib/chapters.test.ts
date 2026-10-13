import { describe, expect, it } from "vitest";

import { chapterIndexAt } from "./chapters";

const CHAPTERS = [
  { title: "Intro", start_seconds: 0, end_seconds: 30 },
  { title: "Planing", start_seconds: 30, end_seconds: 300 },
  { title: "Finish", start_seconds: 300, end_seconds: 600 },
];

describe("chapterIndexAt", () => {
  it("is the last chapter started by then", () => {
    expect(chapterIndexAt(CHAPTERS, 0)).toBe(0);
    expect(chapterIndexAt(CHAPTERS, 29.9)).toBe(0);
    expect(chapterIndexAt(CHAPTERS, 30)).toBe(1);
    expect(chapterIndexAt(CHAPTERS, 1000)).toBe(2);
  });

  it("is -1 before the first chapter or without chapters", () => {
    expect(chapterIndexAt([{ ...CHAPTERS[1]! }], 10)).toBe(-1);
    expect(chapterIndexAt([], 10)).toBe(-1);
  });
});
