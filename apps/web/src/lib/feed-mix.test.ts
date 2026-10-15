import { describe, expect, it } from "vitest";

import {
  MIX_PRESETS,
  MIX_TOPICS,
  currentMix,
  describeMix,
  followedTags,
  formatShare,
  isMixPreset,
  mixLabel,
  mixOf,
  mixSettings,
  parseSharePercent,
  sharePercentText,
  topicCounts,
  topTopics,
  type MixValues,
} from "./feed-mix";

const tag = (slug: string, label = slug) => ({ slug, label });

describe("topTopics", () => {
  it("counts the picks that carry each tag, the most first", () => {
    const picks = [
      { tags: [tag("godot", "Godot"), tag("gamedev", "Game development")] },
      { tags: [tag("godot", "Godot"), tag("rust", "Rust")] },
      { tags: [tag("godot", "Godot")] },
      { tags: [tag("gamedev", "Game development")] },
    ];

    expect(topTopics(picks)).toEqual([
      { slug: "godot", label: "Godot", count: 3 },
      { slug: "gamedev", label: "Game development", count: 2 },
      { slug: "rust", label: "Rust", count: 1 },
    ]);
  });

  it("keeps the top five", () => {
    const picks = Array.from({ length: 8 }, (_, n) => ({
      tags: [tag(`topic-${n}`)],
    }));
    // Topic 7 is on the most picks, topic 6 on the second most.
    picks.push({ tags: [tag("topic-7")] }, { tags: [tag("topic-7")] });
    picks.push({ tags: [tag("topic-6")] });

    const top = topTopics(picks);

    expect(top).toHaveLength(MIX_TOPICS);
    expect(top.map((t) => t.slug).slice(0, 2)).toEqual(["topic-7", "topic-6"]);
    expect(top.map((t) => t.count)).toEqual([3, 2, 1, 1, 1]);
    expect(topTopics(picks, 2)).toHaveLength(2);
    expect(topTopics(picks, 0)).toEqual([]);
  });

  it("breaks ties alphabetically by label", () => {
    const picks = [
      { tags: [tag("b", "Birds")] },
      { tags: [tag("a", "apples")] },
      { tags: [tag("c", "Cats")] },
    ];

    expect(topTopics(picks).map((t) => t.label)).toEqual([
      "apples",
      "Birds",
      "Cats",
    ]);
  });

  it("counts a tag once per pick", () => {
    expect(topTopics([{ tags: [tag("a"), tag("a")] }])).toEqual([
      { slug: "a", label: "a", count: 1 },
    ]);
  });

  it("has nothing to say about picks without tags", () => {
    expect(topTopics([])).toEqual([]);
    expect(topTopics([{}, { tags: [] }])).toEqual([]);
  });
});

describe("topicCounts", () => {
  it("counts every topic, not only the top few", () => {
    const picks = Array.from({ length: 8 }, (_, n) => ({
      tags: [tag(`topic-${n}`)],
    }));

    expect(topicCounts(picks)).toHaveLength(8);
    expect(topicCounts([])).toEqual([]);
  });
});

describe("followedTags", () => {
  const sub = (slug: string, weight: number, label = slug) => ({
    slug,
    label,
    weight,
  });

  it("lists the tags I follow, the ones with most picks today first", () => {
    const subs = [
      sub("rust", 0.5, "Rust"),
      sub("godot", 0.5, "Godot"),
      sub("news", 0.5, "News"),
      sub("birds", 0.5, "Birds"),
    ];
    const counts = new Map([
      ["godot", 9],
      ["news", 1],
      ["rust", 1],
    ]);

    expect(followedTags(subs, counts).map((s) => s.slug)).toEqual([
      "godot",
      "news",
      "rust",
      "birds",
    ]);
  });

  it("leaves out the tags I muted or gave no weight", () => {
    const subs = [sub("a", 0.2), sub("b", 0), sub("c", -0.5), sub("d", 1)];

    expect(followedTags(subs, new Map()).map((s) => s.slug)).toEqual([
      "a",
      "d",
    ]);
  });

  it("doesn't change what it's given", () => {
    const subs = [sub("b", 0.5), sub("a", 0.5)];

    followedTags(subs, new Map());

    expect(subs.map((s) => s.slug)).toEqual(["b", "a"]);
  });
});

describe("the dial", () => {
  const values = (slots: number, share: number, feedSize = 20): MixValues => ({
    feed_size: feedSize,
    feed_exploration_slots: slots,
    feed_max_topic_share: share,
  });

  it("has three presets, from familiar to adventurous", () => {
    expect(
      MIX_PRESETS.map(({ label, slots, share }) => [label, slots, share]),
    ).toEqual([
      ["Familiar", 1, 0.6],
      ["Balanced", 3, 0.4],
      ["Adventurous", 6, 0.25],
    ]);
  });

  it("turns a preset into settings", () => {
    expect(mixSettings("familiar", 20)).toEqual({
      feed_exploration_slots: 1,
      feed_max_topic_share: 0.6,
    });
    expect(mixSettings("adventurous", 20)).toEqual({
      feed_exploration_slots: 6,
      feed_max_topic_share: 0.25,
    });
  });

  it("holds the discovery slots to the size of the feed", () => {
    expect(mixSettings("adventurous", 4).feed_exploration_slots).toBe(4);
    expect(mixSettings("balanced", 2).feed_exploration_slots).toBe(2);
    expect(mixSettings("familiar", 1).feed_exploration_slots).toBe(1);
    expect(mixSettings("balanced", 20).feed_exploration_slots).toBe(3);
  });

  it("recognizes the preset the settings are", () => {
    expect(currentMix(values(1, 0.6))).toBe("familiar");
    expect(currentMix(values(3, 0.4))).toBe("balanced");
    expect(currentMix(values(6, 0.25))).toBe("adventurous");
  });

  it("recognizes a preset whose slots were held to a small feed", () => {
    expect(currentMix(values(4, 0.25, 4))).toBe("adventurous");
    expect(currentMix(values(2, 0.4, 2))).toBe("balanced");
  });

  it("allows for the way a share is stored", () => {
    expect(currentMix(values(3, 0.4000000001))).toBe("balanced");
    expect(currentMix(values(3, 0.403))).toBe("balanced");
  });

  it("calls anything else custom", () => {
    expect(currentMix(values(3, 0.5))).toBe("custom");
    expect(currentMix(values(2, 0.4))).toBe("custom");
    expect(currentMix(values(0, 0.25))).toBe("custom");
    // A preset's share with another preset's slots.
    expect(currentMix(values(1, 0.4))).toBe("custom");
    // Three slots are adventurous only in a feed of three.
    expect(currentMix(values(3, 0.25))).toBe("custom");
  });

  it("says what a choice stands for", () => {
    expect(mixOf("balanced", values(5, 0.5))).toEqual({ slots: 3, share: 0.4 });
    expect(mixOf("adventurous", values(5, 0.5, 4))).toEqual({
      slots: 4,
      share: 0.25,
    });
    expect(mixOf("custom", values(5, 0.5))).toEqual({ slots: 5, share: 0.5 });
  });

  it("names the mix", () => {
    expect(mixLabel("balanced")).toBe("Balanced");
    expect(mixLabel("custom")).toBe("Custom");
  });

  it("knows the presets by name", () => {
    expect(isMixPreset("familiar")).toBe(true);
    expect(isMixPreset("custom")).toBe(false);
    expect(isMixPreset(undefined)).toBe(false);
  });

  it("says what a mix does", () => {
    expect(describeMix(3, 0.4)).toBe(
      "3 discovery slots, and no topic takes more than 40% of the feed.",
    );
    expect(describeMix(1, 0.6)).toBe(
      "1 discovery slot, and no topic takes more than 60% of the feed.",
    );
    expect(describeMix(0, 1)).toBe(
      "0 discovery slots, and no limit on how much one topic takes.",
    );
  });
});

describe("shares as percentages", () => {
  it("formats a share", () => {
    expect(formatShare(0.4)).toBe("40%");
    expect(formatShare(0.25)).toBe("25%");
    expect(formatShare(1)).toBe("100%");
    expect(formatShare(0.1)).toBe("10%");
  });

  it("shows a share for a form field", () => {
    expect(sharePercentText(0.4)).toBe("40");
    expect(sharePercentText(0.07 + 0.01)).toBe("8");
  });

  it("reads a whole percentage from 10 to 100", () => {
    const label = "Most of a feed one topic may take";
    expect(parseSharePercent("40", label)).toEqual({ ok: true, value: 0.4 });
    expect(parseSharePercent(" 25 ", label)).toEqual({ ok: true, value: 0.25 });
    expect(parseSharePercent("10", label)).toEqual({ ok: true, value: 0.1 });
    expect(parseSharePercent("100", label)).toEqual({ ok: true, value: 1 });
    const failed = {
      ok: false,
      message:
        "Most of a feed one topic may take must be a whole number from 10 to 100.",
    };
    for (const raw of ["", "9", "101", "12.5", "lots", "-40"]) {
      expect(parseSharePercent(raw, label)).toEqual(failed);
    }
  });

  it("reads back what it showed", () => {
    for (const share of [0.1, 0.25, 0.29, 0.4, 0.6, 1]) {
      expect(parseSharePercent(sharePercentText(share), "Share")).toEqual({
        ok: true,
        value: share,
      });
    }
  });
});
