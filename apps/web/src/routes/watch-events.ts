import { createFileRoute } from "@tanstack/react-router";

import { handleWatchEvent } from "#/server/watch-events";

/** Where the watch page's beacons go; forwarded to the API's `POST /watch-events`. */
export const Route = createFileRoute("/watch-events")({
  server: {
    handlers: {
      POST: ({ request }) => handleWatchEvent(request),
    },
  },
});
