import { describe, expect, it } from "vitest";

import {
  UNDONE_MESSAGE,
  queuedMessage,
  ratedMessage,
  withRating,
} from "./card-actions";

const video = (video_id: string, rating: number | null = null) => ({
  video_id,
  rating,
});

describe("withRating", () => {
  const items = [video("a"), video("b", 4)];

  it("sets the rating of one video and leaves the others alone", () => {
    const updated = withRating(items, "a", 8);

    expect(updated).toEqual([video("a", 8), video("b", 4)]);
    expect(updated[1]).toBe(items[1]);
    expect(items[0]?.rating).toBeNull();
  });

  it("clears it with null", () => {
    expect(withRating(items, "b", null)).toEqual([video("a"), video("b")]);
  });

  it("returns the items themselves when the video isn't among them", () => {
    expect(withRating(items, "z", 8)).toBe(items);
  });
});

describe("messages", () => {
  it("say what was rated, in words and in numbers", () => {
    expect(ratedMessage("Owls", 8)).toBe("Rated “Owls”: Great, 8 out of 10.");
  });

  it("say which way the queue went", () => {
    expect(queuedMessage("Owls", true)).toBe("Added “Owls” to your queue.");
    expect(queuedMessage("Owls", false)).toBe(
      "Removed “Owls” from your queue.",
    );
  });

  it("confirm an undo briefly", () => {
    expect(UNDONE_MESSAGE).toBe("Undone.");
  });
});
