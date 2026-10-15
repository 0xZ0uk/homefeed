import { describe, expect, it } from "vitest";

import {
  DOMINANT_SHARE,
  FRESH_SUMMARY,
  MIN_PICKS_FOR_BALANCE,
  RATED_WELL,
  SIGNAL_EFFECTS,
  boostMessage,
  describeImbalance,
  describeModel,
  describeMuted,
  describeRatedShare,
  describeRatings,
  describeTopic,
  dismissalReason,
  followedTopics,
  imbalanceOf,
  mutedTopics,
  nameList,
  neutralNudge,
  shareOfPicks,
  stanceOf,
  subscribedMessage,
  suggestionFor,
  summarizeTaste,
  topRatedChannels,
  totalChannels,
  totalDismissals,
  trialMessage,
  unsubscribedMessage,
  type TagTaste,
  type Taste,
} from "./taste";

function tag(label: string, changes: Partial<TagTaste> = {}): TagTaste {
  return {
    tag_id: 1,
    slug: label.toLowerCase().replaceAll(" ", "-"),
    label,
    weight: 0.5,
    hide: false,
    picks: 0,
    watched_picks: 0,
    rating_count: 0,
    average_score: null,
    ...changes,
  };
}

function rated(
  label: string,
  weight: number,
  count: number,
  average: number,
): TagTaste {
  return tag(label, { weight, rating_count: count, average_score: average });
}

function taste(
  tags: TagTaste[],
  changes: Partial<Taste> & { ratings?: number } = {},
): Taste {
  const { ratings = 0, ...rest } = changes;
  return {
    days: 30,
    total_picks: 40,
    min_ratings_to_train: 20,
    tags,
    channel_priors: { love: 0, like: 0, neutral: 0, skeptical: 0 },
    unfollowed_channels: [],
    signals: {
      ratings,
      watched: ratings,
      more_like_this: 0,
      less_like_this: 0,
      dismissals: [],
    },
    ...rest,
  };
}

describe("followedTopics and mutedTopics", () => {
  const tags = [
    tag("Rust", { picks: 1 }),
    tag("Godot", { picks: 12, weight: 0.9 }),
    tag("News", { weight: 0 }),
    tag("crypto", { weight: -0.5 }),
    tag("Cooking", { picks: 12 }),
    tag("Ads", { weight: -1, hide: true }),
  ];

  it("list the followed ones by picks, then A–Z, keeping a zero boost", () => {
    expect(followedTopics(tags).map((t) => t.label)).toEqual([
      "Cooking",
      "Godot",
      "Rust",
      "News",
    ]);
  });

  it("list the muted ones A–Z", () => {
    expect(mutedTopics(tags).map((t) => t.label)).toEqual(["Ads", "crypto"]);
  });

  it("don't change the list they were given", () => {
    const before = tags.map((t) => t.label);
    followedTopics(tags);
    mutedTopics(tags);
    expect(tags.map((t) => t.label)).toEqual(before);
  });
});

describe("shareOfPicks", () => {
  it("is the part of all picks, 0 when nothing was picked", () => {
    expect(shareOfPicks(30, 40)).toBe(0.75);
    expect(shareOfPicks(0, 40)).toBe(0);
    expect(shareOfPicks(3, 0)).toBe(0);
    expect(shareOfPicks(50, 40)).toBe(1);
  });
});

describe("imbalanceOf", () => {
  it("flags a topic with 40% of the picks or more as dominant", () => {
    expect(DOMINANT_SHARE).toBe(0.4);
    expect(imbalanceOf({ weight: 0.5, picks: 30 }, 40)).toEqual({
      kind: "dominant",
      share: 0.75,
      picks: 30,
    });
    expect(imbalanceOf({ weight: 0.5, picks: 16 }, 40)?.kind).toBe("dominant");
    expect(imbalanceOf({ weight: 0.5, picks: 15 }, 40)).toBeNull();
  });

  it("goes by the whole percent the page shows", () => {
    // 21 of 53 is 39.6%, shown as 40%: so it is flagged. 20 of 53 shows 38%.
    expect(imbalanceOf({ weight: 0.5, picks: 21 }, 53)?.kind).toBe("dominant");
    expect(imbalanceOf({ weight: 0.5, picks: 20 }, 53)).toBeNull();
  });

  it("flags a followed topic with one pick or none as rare", () => {
    expect(imbalanceOf({ weight: 0.5, picks: 1 }, 40)).toEqual({
      kind: "rare",
      picks: 1,
    });
    expect(imbalanceOf({ weight: 0, picks: 0 }, 40)).toEqual({
      kind: "rare",
      picks: 0,
    });
    expect(imbalanceOf({ weight: 0.5, picks: 2 }, 40)).toBeNull();
  });

  it("says nothing until enough videos were picked", () => {
    expect(MIN_PICKS_FOR_BALANCE).toBe(10);
    expect(imbalanceOf({ weight: 0.5, picks: 8 }, 9)).toBeNull();
    expect(imbalanceOf({ weight: 0.5, picks: 0 }, 9)).toBeNull();
    expect(imbalanceOf({ weight: 0.5, picks: 0 }, 10)?.kind).toBe("rare");
    expect(imbalanceOf({ weight: 0.5, picks: 4 }, 10)?.kind).toBe("dominant");
  });

  it("says nothing about a muted topic", () => {
    expect(imbalanceOf({ weight: -0.5, picks: 30 }, 40)).toBeNull();
    expect(imbalanceOf({ weight: -0.5, picks: 0 }, 40)).toBeNull();
  });
});

describe("describeImbalance", () => {
  it("says what it takes, or how little shows up", () => {
    expect(
      describeImbalance({ kind: "dominant", share: 0.75, picks: 30 }),
    ).toBe("Takes 75% of your picks");
    expect(describeImbalance({ kind: "rare", picks: 1 })).toBe(
      "Rarely shows up: 1 pick in the last 30 days",
    );
    expect(describeImbalance({ kind: "rare", picks: 0 }, 7)).toBe(
      "Rarely shows up: no picks in the last 7 days",
    );
  });
});

describe("suggestionFor", () => {
  const dominant = { kind: "dominant", share: 0.75, picks: 30 } as const;
  const rare = { kind: "rare", picks: 1 } as const;

  it("lowers the boost of a topic that takes too much", () => {
    expect(suggestionFor({ weight: 0.8 }, dominant)).toEqual({
      weight: 0.5,
      label: "Lower boost to +0.50",
    });
    expect(suggestionFor({ weight: 0.2 }, dominant)).toEqual({
      weight: 0,
      label: "Lower boost to 0.00",
    });
  });

  it("raises the boost of a topic that hardly shows up", () => {
    expect(suggestionFor({ weight: 0.5 }, rare)).toEqual({
      weight: 0.8,
      label: "Raise boost to +0.80",
    });
    expect(suggestionFor({ weight: 0.9 }, rare)).toEqual({
      weight: 1,
      label: "Raise boost to +1.00",
    });
  });

  it("stays on the slider's steps", () => {
    expect(suggestionFor({ weight: 0.15 }, rare)?.weight).toBe(0.45);
    expect(suggestionFor({ weight: 0.95 }, dominant)?.weight).toBe(0.65);
  });

  it("offers nothing when the boost can't move that way", () => {
    expect(suggestionFor({ weight: 0 }, dominant)).toBeNull();
    expect(suggestionFor({ weight: 1 }, rare)).toBeNull();
  });
});

describe("describeTopic", () => {
  it("reads like a channel's line on Subscriptions", () => {
    expect(
      describeTopic({
        picks: 30,
        watched_picks: 12,
        rating_count: 5,
        average_score: 7.43,
      }),
    ).toBe("Watched 12 of 30 picks · avg 7.4 from 5 ratings");
  });

  it("uses singular words and says what is missing", () => {
    expect(
      describeTopic({
        picks: 1,
        watched_picks: 1,
        rating_count: 1,
        average_score: 9,
      }),
    ).toBe("Watched 1 of 1 pick · avg 9.0 from 1 rating");
    expect(
      describeTopic({
        picks: 0,
        watched_picks: 0,
        rating_count: 0,
        average_score: null,
      }),
    ).toBe("No picks in the last 30 days · no ratings yet");
    expect(describeRatings(4, 9)).toBe("avg 9.0 from 4 ratings");
  });
});

describe("describeMuted", () => {
  it("says what the mute does and whether it still gets through", () => {
    expect(describeMuted({ weight: -0.5, hide: false, picks: 0 })).toBe(
      "Suppress −0.50",
    );
    expect(describeMuted({ weight: -0.5, hide: false, picks: 2 })).toBe(
      "Suppress −0.50 · 2 picks in the last 30 days anyway",
    );
    expect(describeMuted({ weight: -1, hide: true, picks: 1 }, 7)).toBe(
      "Suppress −1.00 · hides its videos · 1 pick in the last 7 days anyway",
    );
  });
});

describe("stanceOf", () => {
  it("goes by the ratings once there are two of them", () => {
    expect(stanceOf(rated("a", 0.5, 2, 8))).toBe("love");
    expect(stanceOf(rated("a", 0.5, 3, 6.4))).toBe("lukewarm");
    // However strongly it is boosted.
    expect(stanceOf(rated("a", 1, 3, 4))).toBe("lukewarm");
    expect(stanceOf(rated("a", 0.1, 2, 9))).toBe("love");
  });

  it("goes by the boost for ratings in between, or too few of them", () => {
    expect(stanceOf(rated("a", 0.9, 3, 7))).toBe("love");
    expect(stanceOf(rated("a", 0.5, 3, 7))).toBeNull();
    expect(stanceOf(rated("a", 0.5, 3, 6.5))).toBeNull();
    expect(stanceOf(rated("a", 0.5, 3, 7.9))).toBeNull();
    expect(stanceOf(rated("a", 0.1, 3, 7))).toBe("lukewarm");
    expect(stanceOf(rated("a", 0.9, 1, 2))).toBe("love");
    expect(stanceOf(tag("a", { weight: 0.7 }))).toBe("love");
    expect(stanceOf(tag("a", { weight: 0.2 }))).toBe("lukewarm");
    expect(stanceOf(tag("a", { weight: 0 }))).toBe("lukewarm");
    expect(stanceOf(tag("a", { weight: 0.5 }))).toBeNull();
  });

  it("has none for a muted topic", () => {
    expect(stanceOf(rated("a", -0.5, 5, 9))).toBeNull();
  });
});

describe("nameList", () => {
  it("lists up to three names and counts the rest", () => {
    expect(nameList([])).toBe("");
    expect(nameList(["A"])).toBe("A");
    expect(nameList(["A", "B"])).toBe("A and B");
    expect(nameList(["A", "B", "C"])).toBe("A, B and C");
    expect(nameList(["A", "B", "C", "D"])).toBe("A, B, C and 1 other");
    expect(nameList(["A", "B", "C", "D", "E"])).toBe("A, B, C and 2 others");
  });
});

describe("summarizeTaste", () => {
  it("tells who you love, who you are lukewarm on, and what rarely shows up", () => {
    // The page's own example, but for the last sentence's number.
    expect(
      summarizeTaste(
        taste(
          [
            tag("developer tools", { weight: 0.8, picks: 10 }),
            tag("Godot", { weight: 0.9, picks: 12 }),
            tag("news", { weight: 0.1, picks: 6 }),
            tag("Rust", { weight: 0.5, picks: 1 }),
          ],
          { ratings: 10 },
        ),
      ),
    ).toEqual([
      "You love Godot and developer tools, and you're lukewarm on news.",
      "Rust is followed but rarely shows up: 1 pick in the last 30 days.",
      "You've rated 10 videos; the model starts training at 20.",
    ]);
  });

  it("joins a topic that takes too much and one that hardly shows up", () => {
    expect(
      summarizeTaste(
        taste(
          [
            tag("Game development", { weight: 0.8, picks: 30 }),
            tag("Rust", { weight: 0.8, picks: 1 }),
            tag("Zig", { weight: 0.6, picks: 0 }),
            tag("JavaScript", { weight: 0.5, picks: 9 }),
          ],
          { ratings: 25 },
        ),
      ),
    ).toEqual([
      "You love Game development and Rust.",
      "Game development takes 75% of your picks, while Rust and Zig are followed but rarely show up: 1 pick or fewer each in the last 30 days.",
      "You've rated 25 videos, enough for the model to train on.",
    ]);
  });

  it("starts the balance with a capital, whatever the topic's label", () => {
    expect(
      summarizeTaste(
        taste([tag("hand tools", { picks: 0 }), tag("A", { picks: 15 })]),
      )[1],
    ).toBe(
      "Hand tools is followed but rarely shows up: no picks in the last 30 days.",
    );
  });

  it("keeps lists of names apart with semicolons", () => {
    expect(
      summarizeTaste(
        taste(
          [
            tag("Godot", { weight: 0.9, picks: 12 }),
            tag("Rust", { weight: 0.8, picks: 10 }),
            tag("Zig", { weight: 0.7, picks: 8 }),
            tag("news", { weight: 0.1, picks: 6 }),
            tag("crypto", { weight: -0.5 }),
          ],
          { ratings: 5 },
        ),
      )[0],
    ).toBe(
      "You love Godot, Rust and Zig; you're lukewarm on news; and you've muted crypto.",
    );
    expect(
      summarizeTaste(
        taste(
          [
            tag("Godot", { weight: 0.9, picks: 12 }),
            tag("Rust", { weight: 0.8, picks: 10 }),
            tag("Zig", { weight: 0.7, picks: 8 }),
            tag("news", { weight: 0.1, picks: 6 }),
          ],
          { ratings: 5 },
        ),
      )[0],
    ).toBe("You love Godot, Rust and Zig; you're lukewarm on news.");
  });

  it("names the most taken topics when two take too much", () => {
    const sentences = summarizeTaste(
      taste([
        tag("A", { picks: 20 }),
        tag("B", { picks: 18 }),
        tag("C", { picks: 17 }),
      ]),
    );
    expect(sentences[1]).toBe("A takes 50% of your picks and B takes 45%.");
  });

  it("says what is muted", () => {
    expect(
      summarizeTaste(
        taste(
          [
            tag("Godot", { weight: 0.9, picks: 12 }),
            tag("crypto", { weight: -0.5 }),
            tag("ads", { weight: -1, hide: true }),
          ],
          { ratings: 1 },
        ),
      )[0],
    ).toBe("You love Godot, and you've muted ads and crypto.");
    expect(
      summarizeTaste(
        taste([tag("crypto", { weight: -0.5 })], { ratings: 1 }),
      )[0],
    ).toBe("You've muted crypto.");
  });

  it("counts the topics when none stands out", () => {
    expect(
      summarizeTaste(
        taste([tag("A", { picks: 5 }), tag("B", { picks: 5 })], { ratings: 3 }),
      )[0],
    ).toBe("You follow 2 topics.");
    expect(
      summarizeTaste(
        taste([tag("A", { picks: 5 }), tag("c", { weight: -0.5 })], {
          ratings: 3,
        }),
      )[0],
    ).toBe("You follow 1 topic, and you've muted c.");
  });

  it("leaves out the balance until enough videos were picked", () => {
    const sentences = summarizeTaste(
      taste([tag("A", { picks: 5 })], { total_picks: 5, ratings: 1 }),
    );
    expect(sentences).toHaveLength(2);
  });

  it("says what the feed goes on without topics", () => {
    expect(summarizeTaste(taste([], { ratings: 12 }))).toEqual([
      "You haven't followed any topics yet, so the feed has only your channels and ratings to go on.",
      "You've rated 12 videos; the model starts training at 20.",
    ]);
  });

  it("asks for a first rating when there is none", () => {
    expect(
      summarizeTaste(taste([tag("A", { weight: 0.5, picks: 5 })]))[1],
    ).toBe(
      "You haven't rated any videos yet; the model starts training at 20.",
    );
  });

  it("gives a fresh install one sentence on where to begin", () => {
    expect(summarizeTaste(taste([]))).toEqual([FRESH_SUMMARY]);
  });

  it("never runs to more than three sentences", () => {
    expect(
      summarizeTaste(
        taste(
          [
            tag("A", { weight: 0.9, picks: 30 }),
            tag("B", { weight: 0.1, picks: 0 }),
            tag("c", { weight: -1 }),
          ],
          { ratings: 40 },
        ),
      ).length,
    ).toBeLessThanOrEqual(3);
  });
});

describe("neutralNudge", () => {
  const counts = (neutral: number, others = 0) => ({
    love: others,
    like: 0,
    neutral,
    skeptical: 0,
  });

  it("points out that most channels are on the default", () => {
    expect(neutralNudge({ love: 5, like: 5, neutral: 23, skeptical: 2 })).toBe(
      "23 of your 35 channels are still on Neutral, the default, so the feed only learns about them from your ratings. Set Love, Like or Skeptical on the ones you have a view on.",
    );
  });

  it("speaks for all of them, or the only one", () => {
    expect(neutralNudge(counts(3))).toMatch(
      /^All 3 of your channels are still/,
    );
    expect(neutralNudge(counts(1))).toMatch(
      /^Your channel is still on Neutral, the default, so the feed only learns about it from/,
    );
  });

  it("is quiet when under half are neutral, or there are none", () => {
    expect(neutralNudge(counts(2, 3))).toBeNull();
    expect(neutralNudge(counts(0, 4))).toBeNull();
    expect(neutralNudge(counts(0))).toBeNull();
    expect(neutralNudge(counts(3, 3))).not.toBeNull();
  });

  it("totals the channels", () => {
    expect(totalChannels({ love: 1, like: 2, neutral: 3, skeptical: 4 })).toBe(
      10,
    );
  });
});

describe("topRatedChannels", () => {
  const channels = [
    { channel_id: "a", title: "Alpha" },
    { channel_id: "b", title: "Bravo" },
    { channel_id: "c", title: "Charlie" },
    { channel_id: "d", title: "Delta" },
    { channel_id: "e", title: "echo" },
    { channel_id: "f", title: "Foxtrot" },
    { channel_id: "g", title: "Golf" },
  ];
  const health = new Map([
    ["a", { rating_count: 3, average_score: 8 }],
    ["b", { rating_count: 5, average_score: 8 }],
    ["c", { rating_count: 1, average_score: 10 }], // one lucky video
    ["d", { rating_count: 0, average_score: null }],
    ["e", { rating_count: 2, average_score: 9.5 }],
    ["f", { rating_count: 2, average_score: 6 }],
    // "g" has no numbers at all
  ]);

  it("lists the best averages first, then the most ratings, then A–Z", () => {
    expect(
      topRatedChannels(channels, health).map((r) => r.channel.title),
    ).toEqual(["echo", "Bravo", "Alpha"]);
  });

  it("leaves out channels rated below 7 on average", () => {
    // Foxtrot averages 6.
    expect(
      topRatedChannels(channels, health).some(
        (r) => r.channel.title === "Foxtrot",
      ),
    ).toBe(false);
    expect(
      topRatedChannels(
        [{ channel_id: "x", title: "X" }],
        new Map([["x", { rating_count: 2, average_score: 7 }]]),
      ),
    ).toHaveLength(1);
  });

  it("leaves out channels with fewer than two ratings and caps the list", () => {
    expect(topRatedChannels(channels, health, 2)).toHaveLength(2);
    expect(
      topRatedChannels(channels, health).some(
        (r) => r.channel.title === "Charlie",
      ),
    ).toBe(false);
  });

  it("carries the ratings along", () => {
    expect(topRatedChannels(channels, health)[1]).toEqual({
      channel: channels[1],
      rating_count: 5,
      average_score: 8,
    });
  });
});

describe("RATED_WELL", () => {
  it("says what the API counts as rating a channel well", () => {
    expect(RATED_WELL).toBe("7 or higher on average, from 2 ratings or more");
  });
});

describe("signals", () => {
  it("explains each in one line", () => {
    for (const effect of Object.values(SIGNAL_EFFECTS)) {
      expect(effect).toMatch(/\.$/);
      expect(effect).not.toContain("\n");
    }
  });

  it("words a dismissal without a reason", () => {
    expect(dismissalReason(null)).toBe("No reason given");
    expect(dismissalReason("Clickbait")).toBe("Clickbait");
  });

  it("adds the dismissals up", () => {
    expect(totalDismissals([{ count: 4 }, { count: 1 }])).toBe(5);
    expect(totalDismissals([])).toBe(0);
  });

  it("says how much of what you watched you rated", () => {
    expect(describeRatedShare(10, 26)).toBe(
      "38% of the 26 videos you've watched",
    );
    expect(describeRatedShare(1, 1)).toBe("100% of the 1 video you've watched");
    expect(describeRatedShare(0, 0)).toBeNull();
  });
});

describe("describeModel", () => {
  const version = (id: number, active: boolean) => ({
    id,
    kind: "ridge",
    active,
    created_at: "2026-10-12T03:00:00.000Z",
  });

  it("names the active version and when it was trained", () => {
    expect(describeModel([version(3, false), version(2, true)], 30, 20)).toBe(
      "Version 2 (Ridge) ranks your feed, together with your subscriptions and topics. It was trained on Oct 12, 2026, 03:00 UTC.",
    );
  });

  it("says when no version is active", () => {
    expect(describeModel([version(1, false)], 30, 20)).toBe(
      "No model is active, so the feed is ranked by your subscriptions and topics. Choose a version on the Models page.",
    );
  });

  it("says how far the ratings are from a first model", () => {
    expect(describeModel([], 10, 20)).toBe(
      "No model yet: until there are enough ratings, the feed is ranked by your subscriptions and topics. You have 10 of the 20 it needs to start.",
    );
    expect(describeModel([], 20, 20)).toBe(
      "No model yet: until there are enough ratings, the feed is ranked by your subscriptions and topics. You have enough now, so the next scheduled training should make one.",
    );
  });
});

describe("boostMessage", () => {
  it("says the boost, or that the topic is muted below zero", () => {
    expect(boostMessage("Godot", 0.6)).toBe(
      "Set the boost of Godot to +0.60. The next feed uses it.",
    );
    expect(boostMessage("Godot", 0)).toBe(
      "Set the boost of Godot to 0.00. The next feed uses it.",
    );
    expect(boostMessage("Godot", -0.3)).toBe("Muted Godot (−0.30).");
  });
});

describe("channel messages", () => {
  it("say what was done, and offer the way on after a trial", () => {
    expect(subscribedMessage("Smithing")).toBe("Subscribed to Smithing.");
    expect(trialMessage("Smithing", true)).toBe(
      "Started a 2-week trial of Smithing. You decide in Subscriptions whether to keep it.",
    );
    expect(trialMessage("Smithing", false)).toBe(
      "You're already subscribed to Smithing.",
    );
    expect(unsubscribedMessage("Smithing")).toBe("Unsubscribed from Smithing.");
  });
});
