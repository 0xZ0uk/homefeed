import { describe, expect, it } from "vitest";

import {
  DISMISS_GROUP_LABEL,
  DISMISS_REASONS,
  NOT_DISMISSED,
  dismissedMessage,
  restoredMessage,
  undismissedItems,
  withItemDismissal,
  withSavedDismissal,
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

describe("undoing a dismissal", () => {
  const dismissed = {
    id: 7,
    items: [item(1), item(2, "2026-10-13T08:00:00.000Z")],
  };

  it("restores an item by putting back what it had", () => {
    const restored = withItemDismissal(dismissed, 2, NOT_DISMISSED);

    expect(restored.items[1]).toEqual({
      id: 2,
      title: "Video 2",
      dismissed_at: null,
      dismiss_reason: null,
    });
    expect(undismissedItems(restored.items).map((i) => i.id)).toEqual([1, 2]);
  });
});

describe("messages", () => {
  it("name the video", () => {
    expect(dismissedMessage("Owls at night")).toBe(
      "Dismissed “Owls at night”.",
    );
    expect(restoredMessage("Owls at night")).toBe("Restored “Owls at night”.");
  });

  it("call the menu group by what the dismissal means", () => {
    expect(DISMISS_GROUP_LABEL).toBe("Not for me");
  });
});

describe("withSavedDismissal", () => {
  const dismissedAt = "2026-10-13T08:00:00.000Z";
  const feed = { id: 7, items: [item(1), item(2, dismissedAt)] };

  it("takes the server's timestamp and reason for a dismissal still standing", () => {
    const saved = {
      id: 2,
      dismissed_at: "2026-10-13T08:00:01.250Z",
      dismiss_reason: "Clickbait",
    };

    const updated = withSavedDismissal(feed, saved);

    expect(updated.items[1]).toEqual({
      id: 2,
      title: "Video 2",
      dismissed_at: "2026-10-13T08:00:01.250Z",
      dismiss_reason: "Clickbait",
    });
    expect(updated.items[0]).toBe(feed.items[0]);
  });

  it("leaves an item alone that was restored while the dismissal was saved", () => {
    const restored = { id: 1, items: [item(1), item(2)] };
    const saved = { id: 2, dismissed_at: dismissedAt, dismiss_reason: null };

    expect(withSavedDismissal(restored, saved)).toBe(restored);
  });

  it("leaves an item alone that was dismissed again while a restoration was saved", () => {
    const saved = { id: 2, dismissed_at: null, dismiss_reason: null };

    expect(withSavedDismissal(feed, saved)).toBe(feed);
  });

  it("leaves the other fields of the item as the screen has them", () => {
    const edited = {
      id: 7,
      items: [{ ...item(2, dismissedAt), title: "Edited" }],
    };
    const saved = {
      id: 2,
      dismissed_at: dismissedAt,
      dismiss_reason: "Too long",
    };

    expect(withSavedDismissal(edited, saved).items[0]?.title).toBe("Edited");
  });

  it("ignores an item the feed doesn't have", () => {
    const saved = { id: 9, dismissed_at: dismissedAt, dismiss_reason: null };

    expect(withSavedDismissal(feed, saved)).toBe(feed);
  });
});
