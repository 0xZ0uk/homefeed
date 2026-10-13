import {
  addExternalSource,
  deleteExternalSource,
  listExternalSources,
  updateExternalSource,
  type ExternalSource,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import {
  isSourceKind,
  isSourceSchedule,
  type SourceKind,
  type SourceSchedule,
} from "#/lib/external-sources";
import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for the curation page's sources tab. */

export interface NewSource {
  kind: SourceKind;
  url: string;
  schedule: SourceSchedule;
}

export type SourceResult =
  | { ok: true; source: ExternalSource; created: boolean }
  | { ok: false; message: string };

function checkId(id: unknown): number {
  if (!Number.isInteger(id)) throw new Error("id must be an integer");
  return id as number;
}

const getExternalSources = createServerFn({ method: "GET" }).handler(
  async () => {
    const { data } = await listExternalSources({
      client: apiClient(),
      throwOnError: true,
    });
    return data;
  },
);

export const externalSourcesQuery = queryOptions({
  queryKey: ["external-sources"],
  queryFn: () => getExternalSources(),
});

export const createSource = createServerFn({ method: "POST" })
  .inputValidator((data: NewSource): NewSource => {
    if (!isSourceKind(data.kind)) throw new Error("Unknown source kind");
    if (!isSourceSchedule(data.schedule)) throw new Error("Unknown schedule");
    if (typeof data.url !== "string") throw new Error("url must be a string");
    return { kind: data.kind, url: data.url.trim(), schedule: data.schedule };
  })
  .handler(async ({ data }): Promise<SourceResult> => {
    const {
      data: source,
      error,
      response,
    } = await addExternalSource({ client: apiClient(), body: data });
    if (source) {
      return { ok: true, source, created: response?.status === 201 };
    }
    return {
      ok: false,
      message: apiErrorMessage(
        error,
        response?.status === 422
          ? "Enter a subreddit name or a web address."
          : "Couldn't add that source. Try again later.",
      ),
    };
  });

export const setSourceSchedule = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number; schedule: SourceSchedule }) => {
    if (!isSourceSchedule(data.schedule)) throw new Error("Unknown schedule");
    return { id: checkId(data.id), schedule: data.schedule };
  })
  .handler(async ({ data }) => {
    const { data: source } = await updateExternalSource({
      client: apiClient(),
      path: { source_id: data.id },
      body: { schedule: data.schedule },
      throwOnError: true,
    });
    return source;
  });

export const removeSource = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number }) => ({ id: checkId(data.id) }))
  .handler(async ({ data }) => {
    await deleteExternalSource({
      client: apiClient(),
      path: { source_id: data.id },
      throwOnError: true,
    });
  });
