import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WatchEvent } from "./player-events";
import {
  WATCH_EVENTS_PATH,
  createWatchEventReporter,
  sendWatchEvent,
  toPayload,
  type WatchEventPayload,
} from "./watch-reporter";

const VIDEO = "dQw4w9WgXcQ";

function event(
  type: WatchEvent["type"],
  position: number,
  duration: number | null = 300,
): WatchEvent {
  return { type, position, duration };
}

describe("toPayload", () => {
  it("rounds positions to a tenth of a second", () => {
    expect(toPayload(VIDEO, event("pause", 12.3456, 299.99))).toEqual({
      video_id: VIDEO,
      event_type: "pause",
      position: 12.3,
      duration: 300,
    });
  });

  it("sends an unknown duration as null", () => {
    expect(toPayload(VIDEO, event("close", 0, null)).duration).toBeNull();
    expect(toPayload(VIDEO, event("close", 0, 0)).duration).toBeNull();
  });
});

describe("createWatchEventReporter", () => {
  let sent: WatchEventPayload[];
  const types = () => sent.map((p) => `${p.event_type}@${p.position}`);

  beforeEach(() => {
    vi.useFakeTimers();
    sent = [];
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("sends play, pause, ended and close straight away", () => {
    const reporter = createWatchEventReporter(VIDEO, (p) => sent.push(p));
    reporter.report(event("play", 0));
    reporter.report(event("pause", 10));
    reporter.report(event("play", 10));
    reporter.report(event("ended", 300));
    expect(types()).toEqual(["play@0", "pause@10", "play@10", "ended@300"]);
  });

  it("sends only the last seek of a burst once it's quiet", () => {
    const reporter = createWatchEventReporter(VIDEO, (p) => sent.push(p), {
      seekQuietMs: 1000,
    });
    reporter.report(event("seeked", 20));
    vi.advanceTimersByTime(500);
    reporter.report(event("seeked", 40));
    vi.advanceTimersByTime(500);
    reporter.report(event("seeked", 60));
    expect(sent).toEqual([]);

    vi.advanceTimersByTime(1000);
    expect(types()).toEqual(["seeked@60"]);
    vi.advanceTimersByTime(5000);
    expect(sent).toHaveLength(1);
  });

  it("sends a waiting seek before the next event", () => {
    const reporter = createWatchEventReporter(VIDEO, (p) => sent.push(p));
    reporter.report(event("seeked", 20));
    reporter.report(event("seeked", 90));
    reporter.report(event("close", 95));
    expect(types()).toEqual(["seeked@90", "close@95"]);
    vi.runAllTimers();
    expect(sent).toHaveLength(2);
  });

  it("flushes on demand", () => {
    const reporter = createWatchEventReporter(VIDEO, (p) => sent.push(p));
    reporter.report(event("seeked", 20));
    reporter.flush();
    reporter.flush();
    expect(types()).toEqual(["seeked@20"]);
  });
});

describe("sendWatchEvent", () => {
  const payload = toPayload(VIDEO, event("close", 42));

  it("uses a beacon when it's accepted", async () => {
    const sendBeacon = vi.fn((_url: string, _data: Blob) => true);
    const fetch = vi.fn<typeof globalThis.fetch>();
    sendWatchEvent(payload, { sendBeacon, fetch });

    expect(sendBeacon).toHaveBeenCalledOnce();
    const [url, blob] = sendBeacon.mock.calls[0]!;
    expect(url).toBe(WATCH_EVENTS_PATH);
    expect(blob.type).toBe("application/json");
    expect(JSON.parse(await blob.text())).toEqual(payload);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("falls back to a keepalive fetch", () => {
    const fetch = vi.fn<typeof globalThis.fetch>(() =>
      Promise.reject(new Error("offline")),
    );
    for (const sendBeacon of [undefined, () => false]) {
      fetch.mockClear();
      sendWatchEvent(payload, { sendBeacon, fetch });
      expect(fetch).toHaveBeenCalledWith(
        WATCH_EVENTS_PATH,
        expect.objectContaining({
          method: "POST",
          keepalive: true,
          body: JSON.stringify(payload),
        }),
      );
    }
  });
});
