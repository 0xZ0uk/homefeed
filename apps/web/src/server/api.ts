import { createClient } from "@homefeed/api-client";

/** Client for the internal Python API. Only call this from server functions. */
export function apiClient() {
  return createClient({
    baseUrl: process.env.API_URL ?? "http://localhost:8000",
  });
}
