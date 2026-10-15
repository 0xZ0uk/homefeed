import { describe, expect, it } from "vitest";

import {
  LESS_LIKE_THIS,
  MORE_LIKE_THIS,
  feedbackMessage,
  isSignal,
  nextSignal,
  signalOf,
  withFeedback,
} from "./feedback";

const video = (video_id: string, feedback: number | null = null) => ({
  video_id,
  title: `Video ${video_id}`,
  feedback,
});

describe("isSignal and signalOf", () => {
  it("accept 1 and -1 only", () => {
    expect(isSignal(1)).toBe(true);
    expect(isSignal(-1)).toBe(true);
    for (const other of [0, 2, "1", true, null, undefined]) {
      expect(isSignal(other)).toBe(false);
    }
  });

  it("read the API's feedback as a signal", () => {
    expect(signalOf(1)).toBe(MORE_LIKE_THIS);
    expect(signalOf(-1)).toBe(LESS_LIKE_THIS);
    expect(signalOf(null)).toBeNull();
    expect(signalOf(undefined)).toBeNull();
    expect(signalOf(0)).toBeNull();
  });
});

describe("nextSignal", () => {
  it("sets the signal pressed", () => {
    expect(nextSignal(null, MORE_LIKE_THIS)).toBe(1);
    expect(nextSignal(null, LESS_LIKE_THIS)).toBe(-1);
  });

  it("clears the signal when the pressed one is pressed again", () => {
    expect(nextSignal(1, MORE_LIKE_THIS)).toBeNull();
    expect(nextSignal(-1, LESS_LIKE_THIS)).toBeNull();
  });

  it("switches from the other signal", () => {
    expect(nextSignal(1, LESS_LIKE_THIS)).toBe(-1);
    expect(nextSignal(-1, MORE_LIKE_THIS)).toBe(1);
  });
});

describe("withFeedback", () => {
  const items = [video("a"), video("b", -1), video("c")];

  it("sets the feedback of one video and leaves the others alone", () => {
    const updated = withFeedback(items, "a", MORE_LIKE_THIS);

    expect(updated.map((i) => i.feedback)).toEqual([1, -1, null]);
    expect(updated[1]).toBe(items[1]);
    expect(updated[2]).toBe(items[2]);
    expect(items[0]?.feedback).toBeNull();
  });

  it("clears it with null", () => {
    expect(withFeedback(items, "b", null).map((i) => i.feedback)).toEqual([
      null,
      null,
      null,
    ]);
  });

  it("returns the items themselves when the video isn't among them", () => {
    expect(withFeedback(items, "z", MORE_LIKE_THIS)).toBe(items);
  });
});

describe("feedbackMessage", () => {
  it("names what the video was marked", () => {
    expect(feedbackMessage("Owls", MORE_LIKE_THIS, null)).toBe(
      "Marked “Owls” as more like this.",
    );
    expect(feedbackMessage("Owls", LESS_LIKE_THIS, MORE_LIKE_THIS)).toBe(
      "Marked “Owls” as less like this.",
    );
  });

  it("says what was cleared", () => {
    expect(feedbackMessage("Owls", null, MORE_LIKE_THIS)).toBe(
      "Cleared “more like this” on “Owls”.",
    );
    expect(feedbackMessage("Owls", null, LESS_LIKE_THIS)).toBe(
      "Cleared “less like this” on “Owls”.",
    );
  });
});
