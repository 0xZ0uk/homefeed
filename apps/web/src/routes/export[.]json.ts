import { createFileRoute } from "@tanstack/react-router";
import { getCookie } from "@tanstack/react-start/server";

import { DISPLAY_COOKIE } from "#/lib/display";
import { handleExport } from "#/server/export";

/** The settings page's "Download my data": everything as one JSON file. */
export const Route = createFileRoute("/export.json")({
  server: {
    handlers: {
      GET: () => handleExport(getCookie(DISPLAY_COOKIE)),
    },
  },
});
