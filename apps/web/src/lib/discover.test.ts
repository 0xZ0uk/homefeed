import { describe, expect, it } from "vitest";

import {
  channelUrl,
  featuredByText,
  formatSubscribers,
  hiddenMessage,
  hideKindLabel,
  isChannelId,
} from "./discover";

describe("formatSubscribers", () => {
  it("formats counts compactly", () => {
    expect(formatSubscribers(2_550_000)).toBe("2.6M subscribers");
    expect(formatSubscribers(29_900)).toBe("29.9K subscribers");
    expect(formatSubscribers(812)).toBe("812 subscribers");
    expect(formatSubscribers(1)).toBe("1 subscriber");
  });

  it("is null for unknown counts", () => {
    expect(formatSubscribers(null)).toBeNull();
    expect(formatSubscribers(undefined)).toBeNull();
    expect(formatSubscribers(-1)).toBeNull();
  });
});

describe("featuredByText", () => {
  const channel = (title: string) => ({ title });

  it("names one or two channels", () => {
    expect(featuredByText([channel("Veritasium")])).toBe(
      "Featured by Veritasium",
    );
    expect(featuredByText([channel("A"), channel("B")])).toBe(
      "Featured by A and B",
    );
  });

  it("counts the rest", () => {
    expect(featuredByText(["A", "B", "C"].map(channel))).toBe(
      "Featured by A, B and 1 other",
    );
    expect(featuredByText(["A", "B", "C", "D"].map(channel))).toBe(
      "Featured by A, B and 2 others",
    );
    expect(featuredByText(["A", "B", "C"].map(channel), 3)).toBe(
      "Featured by A, B and C",
    );
  });

  it("says why a lone featuring channel is liked", () => {
    const featuring = (title: string, relation: "love" | "like" | "rated") => ({
      title,
      relation,
    });
    expect(featuredByText([featuring("ManyKudos", "love")])).toBe(
      "Featured by ManyKudos, a channel you love",
    );
    expect(featuredByText([featuring("Veritasium", "like")])).toBe(
      "Featured by Veritasium, a channel you like",
    );
    expect(featuredByText([featuring("Veritasium", "rated")])).toBe(
      "Featured by Veritasium, a channel with a video you rated 7 or higher",
    );
    expect(featuredByText([{ title: "Veritasium", relation: null }])).toBe(
      "Featured by Veritasium",
    );
  });

  it("leaves the relation out when several channels feature it", () => {
    expect(
      featuredByText([
        { title: "A", relation: "love" },
        { title: "B", relation: "like" },
      ]),
    ).toBe("Featured by A and B");
  });

  it("stands in for missing names", () => {
    expect(featuredByText([])).toBe("Featured by a channel you like");
    expect(featuredByText([channel(" ")])).toBe(
      "Featured by a channel you like",
    );
  });
});

describe("channel ids", () => {
  it("builds channel URLs and checks ids", () => {
    const id = "UCHnyfMqiRRG1u-2MsSQLbXA";
    expect(channelUrl(id)).toBe(`https://www.youtube.com/channel/${id}`);
    expect(isChannelId(id)).toBe(true);
    expect(isChannelId("@veritasium")).toBe(false);
    expect(isChannelId(`${id}/videos`)).toBe(false);
  });
});

describe("hide texts", () => {
  it("words the status line and the settings label per kind", () => {
    expect(hiddenMessage("dismissed", "Veritasium")).toBe(
      "Skipped Veritasium in Discover.",
    );
    expect(hiddenMessage("blocked", "Veritasium")).toBe(
      "Hid Veritasium from your feed and Discover.",
    );
    expect(hideKindLabel("dismissed")).toBe("Skipped in Discover");
    expect(hideKindLabel("blocked")).toBe("Hidden from feed and Discover");
  });
});
