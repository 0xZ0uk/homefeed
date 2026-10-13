import { describe, expect, it } from "vitest";

import { DEFAULT_DISPLAY, serializeDisplayPrefs } from "#/lib/display";

import { handleExport } from "./export";

const EXPORT = {
  format: "homefeed-export",
  exported_at: "2026-10-13T09:30:00.000Z",
  ratings: [{ video_id: "dQw4w9WgXcQ", grade: "A+" }],
  settings: { stored: {} },
};

function fetchReturning(response: Response | Error) {
  const urls: string[] = [];
  const fetchImpl = ((input: URL | RequestInfo) => {
    urls.push(String(input));
    return response instanceof Error
      ? Promise.reject(response)
      : Promise.resolve(response);
  }) as typeof fetch;
  return { urls, fetchImpl };
}

describe("handleExport", () => {
  it("downloads the API's export with this browser's display settings", async () => {
    const { urls, fetchImpl } = fetchReturning(Response.json(EXPORT));
    const display = { ...DEFAULT_DISPLAY, thumbnails: true };

    const response = await handleExport(
      serializeDisplayPrefs(display),
      fetchImpl,
      "http://api:8000",
    );

    expect(urls).toEqual(["http://api:8000/export"]);
    expect(response.status).toBe(200);
    expect(response.headers.get("content-disposition")).toBe(
      'attachment; filename="homefeed-export-2026-10-13.json"',
    );
    expect(response.headers.get("content-type")).toMatch(/^application\/json/);
    expect(await response.json()).toEqual({
      ...EXPORT,
      settings: { stored: {}, display },
    });
  });

  it("uses the default display settings without a cookie", async () => {
    const { fetchImpl } = fetchReturning(Response.json(EXPORT));

    const response = await handleExport(undefined, fetchImpl, "http://api");

    const body = (await response.json()) as { settings: unknown };
    expect(body.settings).toEqual({ stored: {}, display: DEFAULT_DISPLAY });
  });

  it("answers 502 when the API fails or can't be reached", async () => {
    for (const upstream of [
      new Response("boom", { status: 500 }),
      new Response("not json"),
      Response.json([1, 2]),
      new Error("connection refused"),
    ]) {
      const { fetchImpl } = fetchReturning(upstream);
      const response = await handleExport(undefined, fetchImpl, "http://api");
      expect(response.status).toBe(502);
    }
  });
});
