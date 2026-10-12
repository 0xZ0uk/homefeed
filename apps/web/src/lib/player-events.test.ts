import { describe, expect, it } from "vitest";

import {
  trackWatchEvents,
  type MediaLike,
  type WatchEvent,
} from "./player-events";

class FakeMedia extends EventTarget implements MediaLike {
  currentTime = 0;
  duration = Number.NaN;

  fire(type: string, at?: number) {
    if (at !== undefined) this.currentTime = at;
    this.dispatchEvent(new Event(type));
  }
}

function track() {
  const media = new FakeMedia();
  const page = new EventTarget();
  const events: WatchEvent[] = [];
  const stop = trackWatchEvents(media, (event) => events.push(event), page);
  const types = () => events.map((e) => `${e.type}@${e.position}`);
  return { media, page, events, stop, types };
}

describe("trackWatchEvents", () => {
  it("reports play, pause and seeks with the position", () => {
    const { media, events, types } = track();
    media.duration = 600;
    media.fire("play", 0);
    media.fire("pause", 42.5);
    media.fire("seeked", 100);

    expect(types()).toEqual(["play@0", "pause@42.5", "seeked@100"]);
    expect(events[0]?.duration).toBe(600);
  });

  it("reports an unknown duration as null", () => {
    const { media, events } = track();
    media.fire("play");
    expect(events[0]).toEqual({ type: "play", position: 0, duration: null });
  });

  it("reports the end, without the pause before it or a close after it", () => {
    const { media, stop, types } = track();
    media.duration = 600;
    media.fire("pause", 600);
    media.fire("ended", 600);
    stop();
    expect(types()).toEqual(["ended@600"]);
  });

  it("closes once when stopped, and after a replay", () => {
    const { media, page, stop, types } = track();
    media.duration = 600;
    media.fire("ended", 600);
    media.fire("play", 0);
    media.fire("pause", 30);
    page.dispatchEvent(new Event("pagehide"));
    stop();
    media.fire("play", 30); // no longer tracked
    expect(types()).toEqual(["ended@600", "play@0", "pause@30", "close@30"]);
  });
});
