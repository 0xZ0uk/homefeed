import { describe, expect, it } from "vitest";

import {
  DISMISS_REASONS,
  undismissedItems,
  withItemDismissal,
} from "./dismiss";

const item = (id: number, dismissed_at: string | null = null) => ({
  id,
  title: `Video ${id}`,
  dismissed_at,
  dismiss_reason: null as string | null,
});

describe("DISMISS_REASONS", () => {
  it("fits the API's 200 character limit and has no duplicates", () => {
    expect(new Set(DISMISS_REASONS).size).toBe(DISMISS_REASONS.length);
    for (const reason of DISMISS_REASONS) {
      expect(reason.length).toBeLessThanOrEqual(200);
    }
  });
});

describe("undismissedItems", () => {
  it("keeps undismissed items in order", () => {
    const items = [item(1), item(2, "2026-10-13T08:00:00.000Z"), item(3)];

    expect(undismissedItems(items).map((i) => i.id)).toEqual([1, 3]);
  });
});

describe("withItemDismissal", () => {
  const feed = { id: 7, items: [item(1), item(2)] };

  it("marks one item dismissed without changing the others", () => {
    const updated = withItemDismissal(feed, 2, {
      dismissed_at: "2026-10-13T08:00:00.000Z",
      dismiss_reason: "Clickbait",
    });

    expect(updated).not.toBe(feed);
    expect(updated.id).toBe(7);
    expect(updated.items[0]).toBe(feed.items[0]);
    expect(updated.items[1]).toEqual({
      id: 2,
      title: "Video 2",
      dismissed_at: "2026-10-13T08:00:00.000Z",
      dismiss_reason: "Clickbait",
    });
    expect(feed.items[1]?.dismissed_at).toBeNull();
  });

  it("takes the server's copy of the item", () => {
    const server = { ...item(1, "2026-10-13T08:00:00.000Z"), title: "New" };

    expect(withItemDismissal(feed, 1, server).items[0]).toEqual(server);
  });

  it("returns the feed itself when the item isn't in it", () => {
    expect(
      withItemDismissal(feed, 9, { dismissed_at: "x", dismiss_reason: null }),
    ).toBe(feed);
  });
});
