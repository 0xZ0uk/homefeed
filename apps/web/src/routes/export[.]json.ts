import { createFileRoute } from "@tanstack/react-router";

import { handleExport } from "#/server/export";

/** The settings page's "Download my data": everything as one JSON file. */
export const Route = createFileRoute("/export.json")({
  server: {
    handlers: {
      GET: () => handleExport(),
    },
  },
});
