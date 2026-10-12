import { describe, expect, it } from "vitest";

import { isFormatId, isVideoId } from "#/lib/ids";

import { proxyToApi } from "./media-proxy";

function recordingFetch(response: Response | Error) {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const fetchImpl = ((input: URL | RequestInfo, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return response instanceof Error
      ? Promise.reject(response)
      : Promise.resolve(response);
  }) as typeof fetch;
  return { calls, fetchImpl };
}

describe("proxyToApi", () => {
  it("forwards the Range header and streams the ranged response", async () => {
    const { calls, fetchImpl } = recordingFetch(
      new Response("0123456789", {
        status: 206,
        headers: {
          "content-type": "video/mp4",
          "content-length": "10",
          "content-range": "bytes 0-9/100",
          "accept-ranges": "bytes",
          "set-cookie": "not=forwarded",
        },
      }),
    );
    const request = new Request("http://web/videos/aaaaaaaaaaa/media/137", {
      headers: { range: "bytes=0-9", cookie: "homefeed_session=secret" },
    });

    const response = await proxyToApi(
      request,
      "/videos/aaaaaaaaaaa/media/137",
      fetchImpl,
      "http://api:8000",
    );

    expect(calls[0]?.url).toBe("http://api:8000/videos/aaaaaaaaaaa/media/137");
    const sent = new Headers(calls[0]?.init?.headers);
    expect(sent.get("range")).toBe("bytes=0-9");
    expect(sent.get("cookie")).toBeNull(); // the session stays in the web app
    expect(response.status).toBe(206);
    expect(response.headers.get("content-range")).toBe("bytes 0-9/100");
    expect(response.headers.get("content-type")).toBe("video/mp4");
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(await response.text()).toBe("0123456789");
  });

  it("passes API errors through", async () => {
    const { fetchImpl } = recordingFetch(
      new Response(null, {
        status: 416,
        headers: { "content-range": "bytes */100" },
      }),
    );
    const response = await proxyToApi(
      new Request("http://web/x"),
      "/x",
      fetchImpl,
      "http://api:8000",
    );
    expect(response.status).toBe(416);
    expect(response.headers.get("content-range")).toBe("bytes */100");
  });

  it("is a 502 when the API is down", async () => {
    const { fetchImpl } = recordingFetch(new TypeError("fetch failed"));
    const response = await proxyToApi(
      new Request("http://web/x"),
      "/x",
      fetchImpl,
      "http://api:8000",
    );
    expect(response.status).toBe(502);
  });
});

describe("ids", () => {
  it("accepts video and format ids only", () => {
    expect(isVideoId("dQw4w9WgXcQ")).toBe(true);
    expect(isVideoId("../health")).toBe(false);
    expect(isFormatId("140-drc")).toBe(true);
    expect(isFormatId("251-1")).toBe(true);
    expect(isFormatId("a/b")).toBe(false);
  });
});
