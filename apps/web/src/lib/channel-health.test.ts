import { describe, expect, it } from "vitest";

import {
  DORMANT_MIN_PICKS,
  describeHealth,
  dormantChannels,
  isChannelSort,
  parseDismissed,
  sortChannels,
  withoutDismissed,
  type ChannelHealth,
} from "./channel-health";

const now = new Date("2026-10-12T09:00:00.000Z");

function health(
  channel_id: string,
  changes: Partial<ChannelHealth> = {},
): ChannelHealth {
  return {
    channel_id,
    last_watched_at: null,
    rating_count: 0,
    average_score: null,
    picks: 0,
    watched_picks: 0,
    ...changes,
  };
}

function channel(
  channel_id: string,
  title = channel_id.toUpperCase(),
  changes: Partial<{
    muted: boolean;
    muted_until: string | null;
    trial_until: string | null;
  }> = {},
) {
  return {
    channel_id,
    title,
    muted: false,
    muted_until: null,
    trial_until: null,
    ...changes,
  };
}

function lookup(...all: ChannelHealth[]) {
  return new Map(all.map((h) => [h.channel_id, h]));
}

describe("describeHealth", () => {
  it("reads like the example: picks, ratings, last watched", () => {
    expect(
      describeHealth(
        health("a", {
          picks: 14,
          watched_picks: 2,
          rating_count: 4,
          average_score: 6.5,
          last_watched_at: "2026-09-21T09:00:00.000Z",
        }),
        now,
      ),
    ).toBe(
      "Watched 2 of 14 picks · avg 6.5 from 4 ratings · last watched 3 weeks ago",
    );
  });

  it("uses singular words and one decimal", () => {
    expect(
      describeHealth(
        health("a", {
          picks: 1,
          watched_picks: 1,
          rating_count: 1,
          average_score: 7,
          last_watched_at: "2026-10-12T08:59:30.000Z",
        }),
        now,
      ),
    ).toBe(
      "Watched 1 of 1 pick · avg 7.0 from 1 rating · last watched just now",
    );
  });

  it("says what is missing", () => {
    expect(describeHealth(health("a"), now)).toBe(
      "No picks in the last 30 days · no ratings yet · never watched",
    );
  });

  it("is null until the numbers have loaded", () => {
    expect(describeHealth(undefined, now)).toBeNull();
  });
});

describe("isChannelSort", () => {
  it("knows the sorts", () => {
    expect(isChannelSort("title")).toBe(true);
    expect(isChannelSort("least-watched")).toBe(true);
    expect(isChannelSort("most-picks")).toBe(true);
    expect(isChannelSort("newest")).toBe(false);
  });
});

describe("sortChannels", () => {
  const channels = [
    channel("c", "carpentry"),
    channel("a", "Birds"),
    channel("b", "Árboles"),
    channel("d", "Zoology"),
  ];
  const ids = (list: { channel_id: string }[]) => list.map((c) => c.channel_id);

  it("sorts A–Z ignoring case and accents, without touching the input", () => {
    const input = [...channels];
    expect(ids(sortChannels(input, undefined, "title"))).toEqual([
      "b",
      "a",
      "c",
      "d",
    ]);
    expect(input).toEqual(channels);
  });

  it("falls back to A–Z without numbers", () => {
    expect(ids(sortChannels(channels, undefined, "most-picks"))).toEqual([
      "b",
      "a",
      "c",
      "d",
    ]);
  });

  it("puts the most picks first, ties by title", () => {
    const stats = lookup(
      health("a", { picks: 3 }),
      health("b", { picks: 9 }),
      health("c", { picks: 9 }),
    );
    expect(ids(sortChannels(channels, stats, "most-picks"))).toEqual([
      "b",
      "c",
      "a",
      "d",
    ]);
  });

  it("puts the least watched first: smaller share of picks watched, then more picks", () => {
    const stats = lookup(
      health("a", { picks: 4, watched_picks: 2 }),
      health("b", { picks: 10, watched_picks: 0 }),
      health("c", { picks: 20, watched_picks: 0 }),
      health("d", { picks: 5, watched_picks: 5 }),
    );
    expect(ids(sortChannels(channels, stats, "least-watched"))).toEqual([
      "c",
      "b",
      "a",
      "d",
    ]);
  });

  it("puts channels without picks after those with, the longest unwatched first", () => {
    const stats = lookup(
      health("a", { picks: 4, watched_picks: 4 }),
      health("b", { last_watched_at: "2026-10-01T00:00:00.000Z" }),
      health("c", { last_watched_at: "2026-08-01T00:00:00.000Z" }),
      // d has no numbers at all: never watched
    );
    expect(ids(sortChannels(channels, stats, "least-watched"))).toEqual([
      "a",
      "d",
      "c",
      "b",
    ]);
  });
});

describe("dormantChannels", () => {
  const picked = (n: number, watched = 0) =>
    ({ picks: n, watched_picks: watched }) satisfies Partial<ChannelHealth>;

  it("lists channels with enough picks and none watched, most picks first", () => {
    const channels = [
      channel("a"),
      channel("b"),
      channel("c"),
      channel("d"),
      channel("e"),
    ];
    const stats = lookup(
      health("a", picked(DORMANT_MIN_PICKS)),
      health("b", picked(DORMANT_MIN_PICKS - 1)),
      health("c", picked(12)),
      health("d", picked(9, 1)),
      // e: no numbers
    );
    expect(
      dormantChannels(channels, stats, now).map((c) => c.channel_id),
    ).toEqual(["c", "a"]);
  });

  it("leaves out channels that are muted or on trial", () => {
    const channels = [
      channel("a", "A", { muted: true }),
      channel("b", "B", { muted_until: "2026-11-01T00:00:00.000Z" }),
      channel("c", "C", { trial_until: "2026-10-20T00:00:00.000Z" }),
      channel("d", "D", { muted_until: "2026-10-01T00:00:00.000Z" }), // ran out
    ];
    const stats = lookup(
      ...channels.map((c) => health(c.channel_id, picked(6))),
    );
    expect(
      dormantChannels(channels, stats, now).map((c) => c.channel_id),
    ).toEqual(["d"]);
  });

  it("is empty until the numbers have loaded", () => {
    expect(dormantChannels([channel("a")], undefined, now)).toEqual([]);
  });
});

describe("dismissed channels", () => {
  it("reads the saved ids and ignores anything else", () => {
    expect(parseDismissed('["a","b"]')).toEqual(["a", "b"]);
    expect(parseDismissed('["a",3,null,"b"]')).toEqual(["a", "b"]);
    expect(parseDismissed('{"a":1}')).toEqual([]);
    expect(parseDismissed("not json")).toEqual([]);
    expect(parseDismissed("")).toEqual([]);
    expect(parseDismissed(null)).toEqual([]);
  });

  it("drops the dismissed channels from a list", () => {
    const list = [channel("a"), channel("b"), channel("c")];
    expect(withoutDismissed(list, ["b", "x"]).map((c) => c.channel_id)).toEqual(
      ["a", "c"],
    );
    expect(withoutDismissed(list, [])).toEqual(list);
  });
});
