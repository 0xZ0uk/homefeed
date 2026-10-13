import { describe, expect, it } from "vitest";

import type { MediaLike } from "./player-events";
import {
  attachSponsorSkip,
  categoryLabel,
  segmentAt,
  type SkipSegment,
} from "./sponsor-skip";

const SPONSOR: SkipSegment = {
  id: "s1",
  category: "sponsor",
  start_seconds: 10,
  end_seconds: 20,
};
const PROMO: SkipSegment = {
  id: "s2",
  category: "selfpromo",
  start_seconds: 20,
  end_seconds: 30,
};
const OUTRO: SkipSegment = {
  id: "s3",
  category: "outro",
  start_seconds: 100,
  end_seconds: 120,
};

/** A `<video>` stand-in: setting `currentTime` seeks like a browser would. */
class FakeMedia extends EventTarget implements MediaLike {
  duration = 600;
  private time = 0;

  get currentTime() {
    return this.time;
  }

  set currentTime(value: number) {
    this.time = value;
    this.dispatchEvent(new Event("seeking"));
    this.dispatchEvent(new Event("timeupdate"));
    this.dispatchEvent(new Event("seeked"));
  }

  /** Playback reaching `time`. */
  playTo(time: number) {
    this.time = time;
    this.dispatchEvent(new Event("timeupdate"));
  }
}

function attach(segments: SkipSegment[] = [SPONSOR, PROMO, OUTRO]) {
  const media = new FakeMedia();
  const skipped: string[] = [];
  const skip = attachSponsorSkip(media, segments, (s) => skipped.push(s.id));
  return { media, skipped, skip };
}

describe("segmentAt", () => {
  it("finds the segment a time falls in, except its last moment", () => {
    expect(segmentAt([SPONSOR, OUTRO], 10)).toBe(SPONSOR);
    expect(segmentAt([SPONSOR, OUTRO], 19)).toBe(SPONSOR);
    expect(segmentAt([SPONSOR, OUTRO], 19.8)).toBeUndefined();
    expect(segmentAt([SPONSOR, OUTRO], 9.9)).toBeUndefined();
    expect(segmentAt([], 10)).toBeUndefined();
  });
});

describe("attachSponsorSkip", () => {
  it("skips a segment when playback runs into it", () => {
    const { media, skipped } = attach();
    media.playTo(5);
    expect(skipped).toEqual([]);

    media.playTo(10.2);

    // Back to back segments are skipped in one go.
    expect(skipped).toEqual(["s1", "s2"]);
    expect(media.currentTime).toBe(30);
  });

  it("skips each segment once per visit", () => {
    const { media, skipped } = attach([OUTRO]);
    media.playTo(100.5);
    expect(media.currentTime).toBe(120);

    media.currentTime = 90; // the viewer goes back
    media.playTo(101);

    expect(skipped).toEqual(["s3"]);
    expect(media.currentTime).toBe(101);
  });

  it("doesn't skip a segment the viewer seeks into", () => {
    const { media, skipped } = attach([OUTRO]);
    media.currentTime = 105;
    media.playTo(106);

    expect(skipped).toEqual([]);
    expect(media.currentTime).toBe(106);
  });

  it("undo plays the skipped segment from its start", () => {
    const { media, skip } = attach([SPONSOR]);
    media.playTo(11);
    expect(media.currentTime).toBe(20);

    skip.undo(SPONSOR);
    media.playTo(12);

    expect(media.currentTime).toBe(12);
  });

  it("stops skipping once stopped", () => {
    const { media, skipped, skip } = attach([SPONSOR]);
    skip.stop();
    media.playTo(11);
    expect(skipped).toEqual([]);
    expect(media.currentTime).toBe(11);
  });
});

describe("categoryLabel", () => {
  it("names known categories and falls back to the raw name", () => {
    expect(categoryLabel("selfpromo")).toBe("self-promotion");
    expect(categoryLabel("brand_new")).toBe("brand new");
  });
});
