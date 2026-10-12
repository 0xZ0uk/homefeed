import {
  activateModel,
  listModels,
  type ModelVersionOut,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { holdoutSize } from "#/lib/models";
import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for the models page. */

/** A model version as the page shows it; the free-form training report is
 * reduced to the parts the page uses. */
export type ModelVersion = Omit<ModelVersionOut, "metrics"> & {
  holdout_size: number | null;
};

export type ActivateResult =
  { ok: true; version: ModelVersion } | { ok: false; message: string };

function toModelVersion({
  metrics,
  ...version
}: ModelVersionOut): ModelVersion {
  return { ...version, holdout_size: holdoutSize(metrics) };
}

const getModels = createServerFn({ method: "GET" }).handler(async () => {
  const { data } = await listModels({
    client: apiClient(),
    throwOnError: true,
  });
  return data.map(toModelVersion);
});

export const modelsQuery = queryOptions({
  queryKey: ["models"],
  queryFn: () => getModels(),
});

export const activateModelVersion = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number }) => {
    if (!Number.isInteger(data.id)) throw new Error("id must be an integer");
    return { id: data.id };
  })
  .handler(async ({ data }): Promise<ActivateResult> => {
    const { data: version, error } = await activateModel({
      client: apiClient(),
      path: { version_id: data.id },
    });
    if (version) return { ok: true, version: toModelVersion(version) };
    return {
      ok: false,
      message: apiErrorMessage(
        error,
        "Couldn't activate that model. Try again later.",
      ),
    };
  });
