import { describe, expect, it } from "vitest";

import {
  LANES,
  emptyReason,
  laneEmptyMessage,
  splitLanes,
  type EmptyReason,
  type LaneId,
} from "./feed-lanes";

describe("splitLanes", () => {
  const item = (id: string, channel_subscribed?: boolean) => ({
    id,
    channel_subscribed,
  });

  it("puts videos from channels I don't subscribe to in the new lane", () => {
    const lanes = splitLanes([
      item("a", true),
      item("b", false),
      item("c", true),
      item("d", false),
    ]);

    expect(lanes.fresh.map((i) => i.id)).toEqual(["b", "d"]);
    expect(lanes.own.map((i) => i.id)).toEqual(["a", "c"]);
  });

  it("keeps the order it was given in both lanes", () => {
    const items = [item("1", false), item("2", true), item("3", false)];

    const lanes = splitLanes([...items].reverse());

    expect(lanes.fresh.map((i) => i.id)).toEqual(["3", "1"]);
    expect(lanes.own.map((i) => i.id)).toEqual(["2"]);
  });

  it("counts a video that doesn't say as one of my channels'", () => {
    const lanes = splitLanes([item("a"), item("b", undefined)]);

    expect(lanes.fresh).toEqual([]);
    expect(lanes.own).toHaveLength(2);
  });

  it("makes two empty lanes of nothing", () => {
    expect(splitLanes([])).toEqual({ fresh: [], own: [] });
  });

  it("names the lanes in the order the page shows them", () => {
    expect(LANES.map(({ id, title }) => [id, title])).toEqual([
      ["fresh", "New to you"],
      ["own", "From your channels"],
    ]);
  });
});

describe("emptyReason", () => {
  it("has none while the lane shows something", () => {
    expect(emptyReason(5, 4, 2)).toBeNull();
    expect(emptyReason(1, 1, 1)).toBeNull();
  });

  it("blames the filter when videos are left but none match", () => {
    expect(emptyReason(5, 4, 0)).toBe("filtered");
  });

  it("blames dismissing when every video was dismissed", () => {
    expect(emptyReason(3, 0, 0)).toBe("dismissed");
  });

  it("says there are none when the feed has none for the lane", () => {
    expect(emptyReason(0, 0, 0)).toBe("none");
  });
});

describe("laneEmptyMessage", () => {
  const message = (lane: LaneId, reason: EmptyReason) =>
    laneEmptyMessage(lane, reason, "Quick");

  it("says what to do about a filter", () => {
    expect(message("own", "filtered")).toBe(
      "Nothing here matches “Quick”. Choose All to see the rest.",
    );
  });

  it("says for each lane that dismissed videos don't come back", () => {
    expect(message("fresh", "dismissed")).toContain("new to you");
    expect(message("own", "dismissed")).toContain("from your channels");
    for (const lane of ["fresh", "own"] as const) {
      expect(message(lane, "dismissed")).toContain("won't come back");
    }
  });

  it("has something to say for every lane and reason", () => {
    for (const { id } of LANES) {
      for (const reason of ["none", "dismissed", "filtered"] as const) {
        expect(message(id, reason).length).toBeGreaterThan(20);
      }
    }
  });
});
