import { exportFilename } from "#/lib/export";
import { apiBaseUrl } from "#/server/api";

/**
 * `GET /export.json` in this app: the API's `GET /export` (not reachable from
 * browsers), sent as a file download.
 * Behind the login like every route (see `src/start.ts`).
 */

/**
 * Build the download. `fetchImpl` and `baseUrl` are the seams for tests.
 */
export async function handleExport(
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = apiBaseUrl(),
): Promise<Response> {
  let data: unknown;
  try {
    const upstream = await fetchImpl(new URL("/export", baseUrl));
    if (!upstream.ok) {
      return new Response("The API couldn't export your data", {
        status: 502,
      });
    }
    data = await upstream.json();
  } catch {
    return new Response("The API could not be reached", { status: 502 });
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return new Response("The API sent an invalid export", { status: 502 });
  }

  const record = data as Record<string, unknown>;
  const exportedAt =
    typeof record.exported_at === "string" ? record.exported_at : "";
  return new Response(JSON.stringify(record, null, 2), {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "content-disposition": `attachment; filename="${exportFilename(exportedAt)}"`,
      "cache-control": "no-store",
    },
  });
}
