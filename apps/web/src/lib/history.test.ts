import { describe, expect, it } from "vitest";

import {
  HISTORY_PAGE_SIZE,
  afterRating,
  describeProgress,
  describeRated,
  isHistoryPageKey,
  neighbourOf,
  pageWindow,
  paramsWith,
  parseHistoryParams,
  progressFraction,
} from "./history";

describe("parseHistoryParams", () => {
  it("keeps the query (whitespace collapsed) and later pages", () => {
    expect(parseHistoryParams({ q: "  hand   planes ", page: 3 })).toEqual({
      q: "hand planes",
      page: 3,
    });
    expect(parseHistoryParams({ q: 42, page: "2" })).toEqual({
      q: "42",
      page: 2,
    });
  });

  it("drops blanks, the first page, bad pages and unknown keys", () => {
    expect(parseHistoryParams({ q: "   ", page: 1, sort: "x" })).toEqual({});
    expect(parseHistoryParams({ page: 0 })).toEqual({});
    expect(parseHistoryParams({ page: 2.5 })).toEqual({});
    expect(parseHistoryParams({ page: "abc" })).toEqual({});
    expect(parseHistoryParams({ q: ["a"] })).toEqual({});
  });

  it("caps the query length", () => {
    expect(parseHistoryParams({ q: "x".repeat(300) }).q).toHaveLength(200);
  });

  it("keeps the unrated filter, as it is written in a URL or as a boolean", () => {
    expect(parseHistoryParams({ unrated: true })).toEqual({ unrated: true });
    expect(parseHistoryParams({ unrated: "true", q: "saw" })).toEqual({
      q: "saw",
      unrated: true,
    });
  });

  it("drops the unrated filter when it is off or not a boolean", () => {
    for (const unrated of [false, "false", "", 1, "yes", null, ["true"]]) {
      expect(parseHistoryParams({ unrated })).toEqual({});
    }
  });
});

describe("paramsWith", () => {
  it("applies a change, keeping the rest", () => {
    expect(paramsWith({ q: "saw" }, { unrated: true })).toEqual({
      q: "saw",
      unrated: true,
    });
    expect(paramsWith({ q: "saw", unrated: true }, { unrated: false })).toEqual(
      { q: "saw" },
    );
    expect(paramsWith({ unrated: true }, { q: "plane" })).toEqual({
      q: "plane",
      unrated: true,
    });
  });

  it("starts over at the first page unless the page is what changes", () => {
    expect(paramsWith({ q: "saw", page: 3 }, { unrated: true })).toEqual({
      q: "saw",
      unrated: true,
    });
    expect(paramsWith({ q: "saw", page: 3 }, { q: "plane" })).toEqual({
      q: "plane",
    });
    expect(paramsWith({ q: "saw", page: 3 }, { page: 4 })).toEqual({
      q: "saw",
      page: 4,
    });
    expect(paramsWith({ q: "saw", page: 3 }, { page: 1 })).toEqual({
      q: "saw",
    });
  });

  it("clears the search with a blank query", () => {
    expect(paramsWith({ q: "saw", unrated: true }, { q: "  " })).toEqual({
      unrated: true,
    });
  });
});

describe("pageWindow", () => {
  it("asks for one more than a page, from the page's start", () => {
    expect(pageWindow({})).toEqual({ limit: HISTORY_PAGE_SIZE + 1, offset: 0 });
    expect(pageWindow({ page: 3 })).toEqual({
      limit: HISTORY_PAGE_SIZE + 1,
      offset: 2 * HISTORY_PAGE_SIZE,
    });
  });
});

describe("describeProgress", () => {
  it("says where I stopped", () => {
    expect(
      describeProgress({
        position: 754,
        resume_position: 754,
        duration: 2400,
        finished: false,
      }),
    ).toBe("Stopped at 12:34 of 40:00");
    expect(
      describeProgress({ position: 65, resume_position: 65, finished: true }),
    ).toBe("Stopped at 1:05");
  });

  it("says finished, or nothing", () => {
    expect(
      describeProgress({
        position: 600,
        resume_position: null,
        finished: true,
      }),
    ).toBe("Finished");
    expect(describeProgress({ position: 2, finished: false })).toBeNull();
  });
});

describe("progressFraction", () => {
  it("is the share watched when it can be resumed", () => {
    expect(
      progressFraction({
        position: 150,
        resume_position: 150,
        duration: 600,
        finished: false,
      }),
    ).toBe(0.25);
    expect(
      progressFraction({
        position: 150,
        resume_position: 150,
        finished: false,
      }),
    ).toBeNull();
    expect(
      progressFraction({ position: 600, duration: 600, finished: true }),
    ).toBeNull();
  });
});

const ENTRIES = [
  { video_id: "aaaaaaaaaaa", score: null },
  { video_id: "bbbbbbbbbbb", score: 4 },
  { video_id: "ccccccccccc" },
];

describe("afterRating", () => {
  it("takes the video out of a list of the unrated", () => {
    expect(afterRating(ENTRIES, "aaaaaaaaaaa", 8, true)).toEqual([
      ENTRIES[1],
      ENTRIES[2],
    ]);
    expect(afterRating(ENTRIES, "zzzzzzzzzzz", 8, true)).toEqual(ENTRIES);
  });

  it("shows the rating in the whole history, leaving the rest alone", () => {
    const after = afterRating(ENTRIES, "ccccccccccc", 9, false);
    expect(after.map((entry) => entry.score)).toEqual([null, 4, 9]);
    expect(after[0]).toBe(ENTRIES[0]);
    expect(ENTRIES[2]).toEqual({ video_id: "ccccccccccc" });
  });
});

describe("isHistoryPageKey", () => {
  it("tells the pages of the unrated from the pages of everything", () => {
    expect(isHistoryPageKey(["history", { unrated: true }], true)).toBe(true);
    expect(isHistoryPageKey(["history", { unrated: true }], false)).toBe(false);
    expect(isHistoryPageKey(["history", { q: "saw" }], false)).toBe(true);
    expect(isHistoryPageKey(["history", {}], true)).toBe(false);
  });

  it("leaves out everything that isn't a page of the history", () => {
    expect(isHistoryPageKey(["history", "summary"], false)).toBe(false);
    expect(isHistoryPageKey(["history"], false)).toBe(false);
    expect(isHistoryPageKey(["video", { unrated: true }], true)).toBe(false);
  });
});

describe("neighbourOf", () => {
  it("is the next entry, else the one before, else nothing", () => {
    expect(neighbourOf(ENTRIES, "aaaaaaaaaaa")?.video_id).toBe("bbbbbbbbbbb");
    expect(neighbourOf(ENTRIES, "bbbbbbbbbbb")?.video_id).toBe("ccccccccccc");
    expect(neighbourOf(ENTRIES, "ccccccccccc")?.video_id).toBe("bbbbbbbbbbb");
    expect(neighbourOf(ENTRIES.slice(0, 1), "aaaaaaaaaaa")).toBeNull();
    expect(neighbourOf(ENTRIES, "zzzzzzzzzzz")).toBeNull();
  });
});

describe("describeRated", () => {
  it("says what was rated and how many are left", () => {
    expect(describeRated("Sharpening a hand plane", 8, 4)).toBe(
      "Rated 8 out of 10: Sharpening a hand plane. 4 left to rate.",
    );
    expect(describeRated("Owls at night", 3, 0)).toBe(
      "Rated 3 out of 10: Owls at night. Everything you watched is rated.",
    );
  });

  it("leaves the count out when it is not known", () => {
    expect(describeRated("Owls at night", 10, null)).toBe(
      "Rated 10 out of 10: Owls at night.",
    );
  });
});
