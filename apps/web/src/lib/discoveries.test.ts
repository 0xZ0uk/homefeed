import type {
  DiscoveredChannelOut,
  DiscoveryRecapOut,
  DiscoveryWindowOut,
} from "@homefeed/api-client";
import { describe, expect, it } from "vitest";

import {
  channelStatusLabel,
  countChange,
  describeChannel,
  followUpReason,
  followUps,
  formatDateRange,
  isFollowed,
  periodWords,
  recapHeadline,
  recapPeriod,
  recapStats,
  shareChange,
  subscribedMessage,
  topicsNote,
  trialStartedMessage,
  unsubscribedMessage,
} from "./discoveries";

function window(
  overrides: Partial<DiscoveryWindowOut> = {},
): DiscoveryWindowOut {
  return {
    start: "2026-10-09",
    end: "2026-10-15",
    new_channels: 0,
    kept_channels: 0,
    liked_channels: 0,
    videos_watched: 0,
    new_channel_videos: 0,
    new_channel_share: null,
    new_topics: 0,
    ...overrides,
  };
}

function recap(
  current: Partial<DiscoveryWindowOut> = {},
  previous: Partial<DiscoveryWindowOut> = {},
  days = 7,
): DiscoveryRecapOut {
  return {
    days,
    top_tier_threshold: 7,
    current: window(current),
    previous: window({ start: "2026-10-02", end: "2026-10-08", ...previous }),
    channels: [],
    topics: [],
  };
}

function channel(
  overrides: Partial<DiscoveredChannelOut> = {},
): DiscoveredChannelOut {
  return {
    channel_id: `UC${"w".repeat(22)}`,
    title: "Woodworking",
    handle: "@wood",
    thumbnail_url: null,
    videos_watched: 1,
    rating_count: 0,
    average_score: null,
    top_score: null,
    status: "not_followed",
    trial_until: null,
    hide_kind: null,
    follow_up: false,
    ...overrides,
  };
}

describe("dates", () => {
  it("writes a range of days in one month with the month once", () => {
    expect(formatDateRange("2026-10-09", "2026-10-15")).toBe("Oct 9–15");
  });

  it("writes a range across months with both", () => {
    expect(formatDateRange("2026-09-28", "2026-10-04")).toBe("Sep 28 – Oct 4");
  });

  it("writes a single day alone", () => {
    expect(formatDateRange("2026-10-15", "2026-10-15")).toBe("Oct 15");
  });

  it("falls back to the raw dates when they are not dates", () => {
    expect(formatDateRange("soon", "later")).toBe("soon – later");
  });

  it("names the two windows in the recap's period", () => {
    expect(recapPeriod(recap())).toBe(
      "The last 7 days (Oct 9–15), compared with the 7 days before (Oct 2–8).",
    );
  });
});

describe("naming the windows", () => {
  it("calls a week's windows this week and last week", () => {
    expect(periodWords(7)).toEqual({
      current: "this week",
      previous: "last week",
      versus: "last week",
    });
  });

  it("names other lengths by their days", () => {
    expect(periodWords(30)).toEqual({
      current: "in the last 30 days",
      previous: "in the 30 days before",
      versus: "the 30 days before",
    });
    expect(periodWords(1)).toEqual({
      current: "today",
      previous: "yesterday",
      versus: "yesterday",
    });
  });
});

describe("the headline", () => {
  it("says how many channels were tried against the week before, and how many were kept", () => {
    expect(
      recapHeadline(
        recap({ new_channels: 4, kept_channels: 1 }, { new_channels: 2 }),
      ),
    ).toBe("You tried 4 new channels this week (2 last week) and kept 1.");
  });

  it("says when none were kept yet", () => {
    expect(recapHeadline(recap({ new_channels: 3 }, { new_channels: 1 }))).toBe(
      "You tried 3 new channels this week (1 last week) and haven't kept any yet.",
    );
    expect(recapHeadline(recap({ new_channels: 1 }))).toBe(
      "You tried 1 new channel this week (0 last week) and haven't kept it yet.",
    );
  });

  it("says when every channel was kept", () => {
    expect(
      recapHeadline(recap({ new_channels: 1, kept_channels: 1 })),
    ).toContain("and kept it.");
    expect(
      recapHeadline(recap({ new_channels: 2, kept_channels: 2 })),
    ).toContain("and kept both.");
    expect(
      recapHeadline(recap({ new_channels: 3, kept_channels: 3 })),
    ).toContain("and kept all of them.");
  });

  it("says when nothing new was tried, with or without a week to compare", () => {
    expect(recapHeadline(recap({}, { new_channels: 3 }))).toBe(
      "You didn't try any new channels this week (3 last week).",
    );
    expect(recapHeadline(recap())).toBe(
      "You didn't try any new channels this week or last week.",
    );
  });

  it("names longer windows by their days", () => {
    expect(
      recapHeadline(
        recap({ new_channels: 5, kept_channels: 2 }, { new_channels: 6 }, 30),
      ),
    ).toBe(
      "You tried 5 new channels in the last 30 days (6 in the 30 days before) and kept 2.",
    );
  });
});

describe("changes", () => {
  it("shows a count that went up, down or stayed", () => {
    expect(countChange(4, 2)).toEqual({ direction: "up", label: "+2" });
    expect(countChange(1, 3)).toEqual({ direction: "down", label: "−2" });
    expect(countChange(2, 2)).toEqual({
      direction: "same",
      label: "No change",
    });
  });

  it("has nothing to compare when both counts are zero", () => {
    expect(countChange(0, 0)).toBeNull();
  });

  it("shows a share in whole percentage points", () => {
    expect(shareChange(0.18, 0.12)).toEqual({
      direction: "up",
      label: "+6 pts",
    });
    expect(shareChange(0.1, 0.25)).toEqual({
      direction: "down",
      label: "−15 pts",
    });
    expect(shareChange(0.5, 0.504)).toEqual({
      direction: "same",
      label: "No change",
    });
  });

  it("has nothing to compare when a share is unknown", () => {
    expect(shareChange(null, 0.2)).toBeNull();
    expect(shareChange(0.2, null)).toBeNull();
  });
});

describe("the totals", () => {
  const stats = recapStats(
    recap(
      {
        new_channels: 4,
        kept_channels: 1,
        liked_channels: 2,
        videos_watched: 22,
        new_channel_videos: 4,
        new_channel_share: 4 / 22,
      },
      {
        new_channels: 2,
        kept_channels: 2,
        liked_channels: 0,
        videos_watched: 10,
        new_channel_videos: 1,
        new_channel_share: 0.1,
      },
    ),
  );

  it("has the four figures in order, each beside the week before", () => {
    expect(
      stats.map(({ key, label, value, detail }) => [key, label, value, detail]),
    ).toEqual([
      ["tried", "New channels tried", "4", "2 last week"],
      ["kept", "Channels kept", "1", "2 last week"],
      ["liked", "Channels rated 7 or higher", "2", "0 last week"],
      [
        "share",
        "Videos from new channels",
        "18%",
        "4 of 22 videos · 10% last week",
      ],
    ]);
  });

  it("marks how each moved", () => {
    expect(stats.map((stat) => stat.change?.label)).toEqual([
      "+2",
      "−1",
      "+2",
      "+8 pts",
    ]);
  });

  it("leaves the share open when nothing was watched", () => {
    const quiet = recapStats(recap());

    expect(quiet.map((stat) => stat.change)).toEqual([null, null, null, null]);
    expect(quiet[3]).toMatchObject({ value: "–", detail: "No videos watched" });
  });

  it("says when nothing was watched in the week before", () => {
    const stat = recapStats(
      recap({
        videos_watched: 5,
        new_channel_videos: 1,
        new_channel_share: 0.2,
      }),
    )[3];

    expect(stat).toMatchObject({
      value: "20%",
      detail: "1 of 5 videos · no videos last week",
      change: null,
    });
  });

  it("follows the threshold the API counts by", () => {
    const strict = { ...recap(), top_tier_threshold: 8 };

    expect(recapStats(strict)[2]?.label).toBe("Channels rated 8 or higher");
  });
});

describe("a channel", () => {
  const now = new Date("2026-10-15T12:00:00.000Z");

  it("says where it stands", () => {
    expect(channelStatusLabel(channel({ status: "subscribed" }), now)).toBe(
      "Subscribed",
    );
    expect(channelStatusLabel(channel({ status: "hidden" }), now)).toBe(
      "Hidden",
    );
    expect(channelStatusLabel(channel({ status: "not_followed" }), now)).toBe(
      "Not followed",
    );
  });

  it("counts the days left of a trial, a started day as a day", () => {
    const trial = (trial_until: string | null) =>
      channelStatusLabel(channel({ status: "trial", trial_until }), now);

    expect(trial("2026-10-29T12:00:00.000Z")).toBe("On trial · 14 days left");
    expect(trial("2026-10-16T01:00:00.000Z")).toBe("On trial · 1 day left");
    expect(trial("2026-10-15T11:00:00.000Z")).toBe("On trial · ends today");
    expect(trial(null)).toBe("On trial · ends today");
  });

  it("knows which channels I follow", () => {
    expect(isFollowed({ status: "subscribed" })).toBe(true);
    expect(isFollowed({ status: "trial" })).toBe(true);
    expect(isFollowed({ status: "hidden" })).toBe(false);
    expect(isFollowed({ status: "not_followed" })).toBe(false);
  });

  it("describes what was watched and how it was rated", () => {
    expect(describeChannel(channel({ videos_watched: 2 }))).toBe(
      "2 videos watched · not rated",
    );
    expect(
      describeChannel(
        channel({ videos_watched: 1, rating_count: 1, average_score: 9 }),
      ),
    ).toBe("1 video watched · rated 9");
    expect(
      describeChannel(
        channel({ videos_watched: 3, rating_count: 2, average_score: 8.5 }),
      ),
    ).toBe("3 videos watched · average rating 8.5 from 2 ratings");
    expect(
      describeChannel(
        channel({ videos_watched: 3, rating_count: 3, average_score: 8 }),
      ),
    ).toBe("3 videos watched · average rating 8.0 from 3 ratings");
  });
});

describe("follow-ups", () => {
  it("keeps the channels the API marks, in order", () => {
    const a = channel({ channel_id: "a", follow_up: true });
    const b = channel({ channel_id: "b" });
    const c = channel({ channel_id: "c", follow_up: true });

    expect(followUps([a, b, c])).toEqual([a, c]);
    expect(followUps([b])).toEqual([]);
  });

  it("gives the best rating as the reason", () => {
    expect(followUpReason(channel({ top_score: 9 }))).toBe(
      "Best rating: Excellent, 9 out of 10",
    );
    expect(followUpReason(channel({ top_score: null }))).toBeNull();
  });

  it("says when the channel is one I had hidden", () => {
    expect(
      followUpReason(channel({ top_score: 8, hide_kind: "blocked" })),
    ).toBe("Best rating: Great, 8 out of 10 · Hidden from feed and Discover");
    expect(
      followUpReason(channel({ top_score: 8, hide_kind: "dismissed" })),
    ).toBe("Best rating: Great, 8 out of 10 · Skipped in Discover");
  });

  it("words what each action did", () => {
    expect(subscribedMessage("Metalworking", true)).toBe(
      "Subscribed to Metalworking.",
    );
    expect(subscribedMessage("Metalworking", false)).toBe(
      "You're already subscribed to Metalworking.",
    );
    expect(trialStartedMessage("Metalworking", true)).toBe(
      "Started a 2-week trial of Metalworking. You decide in Subscriptions whether to keep it.",
    );
    expect(trialStartedMessage("Metalworking", false)).toBe(
      "You're already subscribed to Metalworking.",
    );
    expect(unsubscribedMessage("Metalworking")).toBe(
      "Unsubscribed from Metalworking.",
    );
  });
});

describe("topics", () => {
  it("says how many of the new topics are shown when some are left out", () => {
    expect(topicsNote(12, 15)).toBe("Showing the 12 most watched of 15.");
    expect(topicsNote(3, 3)).toBeNull();
  });
});
