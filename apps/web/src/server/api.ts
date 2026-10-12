import { createClient } from "@homefeed/api-client";

/** Base URL of the internal Python API (not reachable from browsers). */
export function apiBaseUrl(): string {
  return process.env.API_URL ?? "http://localhost:8000";
}

/** Client for the internal Python API. Only call this from server functions. */
export function apiClient() {
  return createClient({ baseUrl: apiBaseUrl() });
}

/**
 * The human-readable message from an API error body (`{"detail": "..."}`), or
 * `fallback` when there isn't one (e.g. request validation errors, whose
 * `detail` is a list).
 */
export function apiErrorMessage(error: unknown, fallback: string): string {
  if (
    typeof error === "object" &&
    error !== null &&
    "detail" in error &&
    typeof error.detail === "string" &&
    error.detail
  ) {
    return error.detail;
  }
  return fallback;
}
