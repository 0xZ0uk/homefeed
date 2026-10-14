import { describe, expect, it } from "vitest";

import type { Chapter } from "./chapters";
import {
  chapterPieces,
  describeTime,
  fractionAt,
  SEGMENT_COLORS,
  segmentColor,
  SEGMENT_FALLBACK_COLOR,
  timelineRanges,
} from "./player-timeline";
import type { SkipSegment } from "./sponsor-skip";

const SPONSOR: SkipSegment = {
  id: "s1",
  category: "sponsor",
  start_seconds: 10,
  end_seconds: 20,
};
const OUTRO: SkipSegment = {
  id: "s2",
  category: "outro",
  start_seconds: 90,
  end_seconds: 130,
};

const INTRO: Chapter = { title: "Intro", start_seconds: 0, end_seconds: 30 };
const MAIN: Chapter = { title: "Main", start_seconds: 30, end_seconds: 100 };

describe("segmentColor", () => {
  it("maps categories to variables, with a fallback", () => {
    expect(segmentColor("sponsor")).toBe("var(--sb-sponsor)");
    expect(segmentColor("music_offtopic")).toBe("var(--sb-music-offtopic)");
    expect(segmentColor("nope")).toBe(SEGMENT_FALLBACK_COLOR);
    expect(Object.keys(SEGMENT_COLORS)).toHaveLength(9);
  });
});

describe("timelineRanges", () => {
  it("places segments as fractions of the duration", () => {
    expect(timelineRanges([SPONSOR], 100)).toEqual([
      { segment: SPONSOR, left: 0.1, width: 0.1 },
    ]);
  });

  it("clamps a segment running past the end", () => {
    const [range] = timelineRanges([OUTRO], 100);
    expect(range?.left).toBe(0.9);
    expect(range?.width).toBeCloseTo(0.1);
  });

  it("drops segments outside the bar or empty", () => {
    const after = { ...SPONSOR, id: "x", start_seconds: 100, end_seconds: 110 };
    const empty = { ...SPONSOR, id: "y", start_seconds: 5, end_seconds: 5 };
    expect(timelineRanges([after, empty], 100)).toEqual([]);
  });

  it("is empty without a duration", () => {
    expect(timelineRanges([SPONSOR], null)).toEqual([]);
    expect(timelineRanges([SPONSOR], 0)).toEqual([]);
  });
});

describe("chapterPieces", () => {
  it("is one piece without chapters", () => {
    expect(chapterPieces([], 100)).toEqual([
      { start: 0, end: 100, left: 0, width: 1 },
    ]);
  });

  it("is one piece without a duration", () => {
    expect(chapterPieces([INTRO], null)).toEqual([
      { start: 0, end: 0, left: 0, width: 1 },
    ]);
  });

  it("splits at chapter starts and ends at the duration", () => {
    expect(chapterPieces([INTRO, MAIN], 120)).toEqual([
      { start: 0, end: 30, left: 0, width: 0.25, title: "Intro" },
      { start: 30, end: 120, left: 0.25, width: 0.75, title: "Main" },
    ]);
  });

  it("adds an untitled piece before a chapter that starts late", () => {
    const pieces = chapterPieces([MAIN], 120);
    expect(pieces).toHaveLength(2);
    expect(pieces[0]).toEqual({ start: 0, end: 30, left: 0, width: 0.25 });
    expect(pieces[0]).not.toHaveProperty("title");
    expect(pieces[1]?.title).toBe("Main");
    expect(pieces[1]).toMatchObject({ start: 30, end: 120 });
  });

  it("ignores chapters past the end and sorts the rest", () => {
    const late: Chapter = {
      title: "Late",
      start_seconds: 500,
      end_seconds: 600,
    };
    const pieces = chapterPieces([late, MAIN, INTRO], 120);
    expect(pieces.map((p) => p.title)).toEqual(["Intro", "Main"]);
    expect(pieces.at(-1)?.end).toBe(120);
  });

  it("covers the whole bar when only late chapters exist", () => {
    const late: Chapter = {
      title: "Late",
      start_seconds: 500,
      end_seconds: 600,
    };
    expect(chapterPieces([late], 120)).toEqual([
      { start: 0, end: 120, left: 0, width: 1 },
    ]);
  });
});

describe("describeTime", () => {
  it("names the chapter and the segment at a time", () => {
    expect(describeTime(15, [INTRO, MAIN], [SPONSOR, OUTRO])).toEqual({
      chapterTitle: "Intro",
      segment: SPONSOR,
    });
    expect(describeTime(40, [INTRO, MAIN], [SPONSOR, OUTRO])).toEqual({
      chapterTitle: "Main",
      segment: null,
    });
  });

  it("includes a segment's start but not its end", () => {
    expect(describeTime(10, [], [SPONSOR]).segment).toBe(SPONSOR);
    expect(describeTime(20, [], [SPONSOR]).segment).toBeNull();
  });

  it("has no chapter before the first one or without chapters", () => {
    expect(describeTime(5, [MAIN], []).chapterTitle).toBeNull();
    expect(describeTime(5, [], []).chapterTitle).toBeNull();
  });
});

describe("fractionAt", () => {
  const rect = { left: 100, width: 200 };

  it("measures along the rect", () => {
    expect(fractionAt(100, rect)).toBe(0);
    expect(fractionAt(150, rect)).toBe(0.25);
    expect(fractionAt(300, rect)).toBe(1);
  });

  it("clamps outside the rect", () => {
    expect(fractionAt(0, rect)).toBe(0);
    expect(fractionAt(999, rect)).toBe(1);
  });

  it("is 0 for an empty rect", () => {
    expect(fractionAt(5, { left: 0, width: 0 })).toBe(0);
  });
});
