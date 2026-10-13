import {
  getExtractorStatus,
  type ExtractorStatusOut,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { parseStatusHours } from "#/lib/status";
import { apiClient } from "#/server/api";

/** Server functions for the status page. */

export type ExtractorStatus = ExtractorStatusOut;
export type OperationStatus = ExtractorStatusOut["operations"][number];
export type FailedEvent = ExtractorStatusOut["recent_failures"][number];
export type SmokeTestRun = NonNullable<ExtractorStatusOut["last_smoke_test"]>;

const fetchExtractorStatus = createServerFn({ method: "GET" })
  .inputValidator((data: { hours: number }) => ({
    hours: parseStatusHours(data.hours),
  }))
  .handler(async ({ data }): Promise<ExtractorStatus> => {
    const { data: status } = await getExtractorStatus({
      client: apiClient(),
      query: { hours: data.hours },
      throwOnError: true,
    });
    return status;
  });

/** Extraction health over the last `hours`. */
export function extractorStatusQuery(hours: number) {
  return queryOptions({
    queryKey: ["status", "extractors", hours],
    queryFn: () => fetchExtractorStatus({ data: { hours } }),
    // Fresh numbers on every visit, but not on every focus.
    staleTime: 30 * 1000,
  });
}
