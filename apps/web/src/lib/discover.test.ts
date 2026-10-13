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
      "Dismissed Veritasium.",
    );
    expect(hiddenMessage("blocked", "Veritasium")).toBe(
      "Veritasium's videos won't show in your feed.",
    );
    expect(hideKindLabel("dismissed")).toBe("Dismissed from Discover");
    expect(hideKindLabel("blocked")).toBe("Hidden from feed");
  });
});
