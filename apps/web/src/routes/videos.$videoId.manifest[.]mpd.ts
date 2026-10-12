import { createFileRoute } from "@tanstack/react-router";

import { isVideoId } from "#/lib/ids";
import { notFound, proxyToApi } from "#/server/media-proxy";

/**
 * The DASH manifest for the player, from the internal API. Its media URLs are
 * relative (`media/{itag}`), so the player fetches them from this app too.
 */
export const Route = createFileRoute("/videos/$videoId/manifest.mpd")({
  server: {
    handlers: {
      GET: ({ request, params }) => {
        if (!isVideoId(params.videoId)) return notFound();
        return proxyToApi(request, `/videos/${params.videoId}/manifest.mpd`);
      },
    },
  },
});
