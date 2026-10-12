import { describe, expect, it, vi } from "vitest";

import {
  handleWatchEvent,
  isSameOrigin,
  parseWatchEvent,
} from "./watch-events";

const VIDEO = "dQw4w9WgXcQ";
const URL_ = "http://homefeed.local/watch-events";
const valid = {
  video_id: VIDEO,
  event_type: "pause",
  position: 12.5,
  duration: 300,
};

function request(body: unknown, headers: Record<string, string> = {}) {
  return new Request(URL_, {
    method: "POST",
    body: typeof body === "string" ? body : JSON.stringify(body),
    headers: { "content-type": "application/json", ...headers },
  });
}

describe("parseWatchEvent", () => {
  it("accepts a valid event", () => {
    expect(parseWatchEvent(valid)).toEqual(valid);
  });

  it("treats a missing duration as unknown", () => {
    const { duration: _, ...rest } = valid;
    expect(parseWatchEvent(rest)).toEqual({ ...rest, duration: null });
  });

  it("rejects invalid events", () => {
    for (const body of [
      null,
      "pause",
      { ...valid, video_id: "nope" },
      { ...valid, event_type: "timeupdate" },
      { ...valid, position: -1 },
      { ...valid, position: "12" },
      { ...valid, position: Number.NaN },
      { ...valid, duration: 0 },
      { ...valid, duration: 1e9 },
    ]) {
      expect(parseWatchEvent(body)).toBeNull();
    }
  });
});

describe("isSameOrigin", () => {
  it("trusts Sec-Fetch-Site when present", () => {
    expect(
      isSameOrigin(request(valid, { "sec-fetch-site": "same-origin" })),
    ).toBe(true);
    expect(
      isSameOrigin(request(valid, { "sec-fetch-site": "cross-site" })),
    ).toBe(false);
    expect(
      isSameOrigin(request(valid, { "sec-fetch-site": "same-site" })),
    ).toBe(false);
  });

  it("falls back to Origin", () => {
    expect(
      isSameOrigin(request(valid, { origin: "http://homefeed.local" })),
    ).toBe(true);
    expect(
      isSameOrigin(request(valid, { origin: "http://evil.example" })),
    ).toBe(false);
    expect(isSameOrigin(request(valid))).toBe(true);
  });
});

describe("handleWatchEvent", () => {
  it("forwards a valid event", async () => {
    const record = vi.fn(async () => true);
    const response = await handleWatchEvent(request(valid), record);
    expect(response.status).toBe(204);
    expect(record).toHaveBeenCalledWith(valid);
  });

  it("refuses cross-site requests", async () => {
    const record = vi.fn(async () => true);
    const response = await handleWatchEvent(
      request(valid, { "sec-fetch-site": "cross-site" }),
      record,
    );
    expect(response.status).toBe(403);
    expect(record).not.toHaveBeenCalled();
  });

  it("rejects bad bodies", async () => {
    const record = vi.fn(async () => true);
    expect((await handleWatchEvent(request("{"), record)).status).toBe(400);
    expect(
      (await handleWatchEvent(request({ ...valid, position: -1 }), record))
        .status,
    ).toBe(400);
    expect(record).not.toHaveBeenCalled();
  });

  it("reports API failures as 502", async () => {
    expect(
      (await handleWatchEvent(request(valid), async () => false)).status,
    ).toBe(502);
    expect(
      (
        await handleWatchEvent(request(valid), async () => {
          throw new Error("down");
        })
      ).status,
    ).toBe(502);
  });
});
