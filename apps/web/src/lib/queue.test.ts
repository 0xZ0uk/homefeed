import { describe, expect, it } from "vitest";

import {
  nextInQueue,
  parseVideoInput,
  queueButtonLabel,
  withItemMoved,
  withoutItem,
} from "./queue";

const queue = (...videoIds: string[]) =>
  videoIds.map((video_id, position) => ({
    id: position + 1,
    video_id,
    position,
  }));

const videoIds = (items: { video_id: string; position: number }[]) => {
  expect(items.map((item) => item.position)).toEqual(
    items.map((_, index) => index),
  );
  return items.map((item) => item.video_id);
};

describe("withItemMoved", () => {
  const items = queue("a", "b", "c", "d");

  it.each([
    [1, 2, ["b", "c", "a", "d"]],
    [4, 0, ["d", "a", "b", "c"]],
    [2, 2, ["a", "c", "b", "d"]],
    [3, 1, ["a", "c", "b", "d"]],
    [1, 99, ["b", "c", "d", "a"]],
    [4, -1, ["d", "a", "b", "c"]],
  ])("moves item %i to %i", (id, position, expected) => {
    expect(videoIds(withItemMoved(items, id, position))).toEqual(expected);
  });

  it("leaves the queue alone for an unknown item", () => {
    expect(withItemMoved(items, 42, 0)).toBe(items);
  });

  it("keeps unmoved items as they were", () => {
    const moved = withItemMoved(items, 3, 2);
    expect(moved[0]).toBe(items[0]);
    expect(moved[3]).toBe(items[3]);
  });
});

describe("withoutItem", () => {
  it("removes the item and renumbers the rest", () => {
    expect(videoIds(withoutItem(queue("a", "b", "c"), 2))).toEqual(["a", "c"]);
  });
});

describe("nextInQueue", () => {
  const items = queue("a", "b", "c");

  it("is the item after a queued video", () => {
    expect(nextInQueue(items, "a")?.video_id).toBe("b");
    expect(nextInQueue(items, "c")).toBeNull();
  });

  it("is the first item for a video that isn't queued", () => {
    expect(nextInQueue(items, "z")?.video_id).toBe("a");
    expect(nextInQueue([], "z")).toBeNull();
  });
});

describe("parseVideoInput", () => {
  const id = "dQw4w9WgXcQ";

  it.each([
    id,
    `  ${id} `,
    `https://www.youtube.com/watch?v=${id}`,
    `https://www.youtube.com/watch?v=${id}&t=42s&list=PL123`,
    `youtube.com/watch?v=${id}`,
    `https://m.youtube.com/watch?v=${id}`,
    `https://music.youtube.com/watch?v=${id}`,
    `https://youtu.be/${id}?si=abc`,
    `youtu.be/${id}`,
    `https://www.youtube.com/shorts/${id}`,
    `https://www.youtube.com/live/${id}`,
    `https://www.youtube-nocookie.com/embed/${id}`,
  ])("reads %s", (input) => {
    expect(parseVideoInput(input)).toBe(id);
  });

  it.each([
    "",
    "not a video",
    "dQw4w9WgXc",
    "https://www.youtube.com/@channel",
    "https://www.youtube.com/playlist?list=PL123",
    `https://example.com/watch?v=${id}`,
    `https://www.youtube.com/watch?v=short`,
  ])("rejects %j", (input) => {
    expect(parseVideoInput(input)).toBeNull();
  });
});

describe("queueButtonLabel", () => {
  it("names the queue, with its length once there is one", () => {
    expect(queueButtonLabel(0)).toBe("Queue");
    expect(queueButtonLabel(1)).toBe("Queue, 1 video");
    expect(queueButtonLabel(12)).toBe("Queue, 12 videos");
  });
});
