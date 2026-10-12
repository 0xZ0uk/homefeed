import { apiBaseUrl } from "#/server/api";

/**
 * Forwarding playback requests (DASH manifest and media byte ranges) from the
 * browser to the internal API. The API isn't reachable from browsers, so the
 * player fetches `/videos/...` from this app, behind the login (the global auth
 * middleware in `src/start.ts` covers these server routes).
 */

/** Request headers the API needs for ranged reads. */
const FORWARDED_REQUEST_HEADERS = ["range", "if-range"];

/** Response headers passed back to the player. */
const FORWARDED_RESPONSE_HEADERS = [
  "content-type",
  "content-length",
  "content-range",
  "accept-ranges",
  "cache-control",
];

/**
 * Forward a GET to `path` on the API, streaming the response body back.
 * `fetchImpl` is the seam for tests.
 */
export async function proxyToApi(
  request: Request,
  path: string,
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = apiBaseUrl(),
): Promise<Response> {
  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }

  let upstream: Response;
  try {
    upstream = await fetchImpl(new URL(path, baseUrl), {
      headers,
      // Stop the upstream read when the player cancels (seeks, quality switch).
      signal: request.signal,
    });
  } catch (error) {
    if (request.signal.aborted) throw error;
    return new Response("The API could not be reached", { status: 502 });
  }

  const responseHeaders = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) responseHeaders.set(name, value);
  }
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

/** 404 for ids that can't be videos or streams, without asking the API. */
export function notFound(): Response {
  return new Response("Not found", { status: 404 });
}
