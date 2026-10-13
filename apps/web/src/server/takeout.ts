import { importTakeout, type ImportReport } from "@homefeed/api-client";
import { createServerFn } from "@tanstack/react-start";

import { parseTakeoutForm } from "#/lib/takeout";
import { apiClient, apiErrorMessage } from "#/server/api";

/** Server function for the settings page's Takeout import. */

export type TakeoutImportResult =
  { ok: true; report: ImportReport } | { ok: false; message: string };

/**
 * Upload a Takeout watch history (multipart form: `file`, and `subscribe` with
 * `subscribe_min_watches`) and forward it to the API's `POST /import/takeout`.
 */
export const uploadTakeout = createServerFn({ method: "POST" })
  .inputValidator((data: FormData) => {
    if (!(data instanceof FormData)) throw new Error("Expected form data");
    return data;
  })
  .handler(async ({ data }): Promise<TakeoutImportResult> => {
    const parsed = parseTakeoutForm(data);
    if (!parsed.ok) return parsed;
    const { data: report, error } = await importTakeout({
      client: apiClient(),
      body: {
        file: parsed.file,
        ...(parsed.options.subscribeMinWatches !== null && {
          subscribe_min_watches: parsed.options.subscribeMinWatches,
        }),
      },
    });
    if (report) return { ok: true, report };
    return {
      ok: false,
      message: apiErrorMessage(
        error,
        "Couldn't import that file. Try again later.",
      ),
    };
  });
