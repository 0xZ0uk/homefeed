import { createFileRoute } from "@tanstack/react-router";

import { isFormatId, isVideoId } from "#/lib/ids";
import { notFound, proxyToApi } from "#/server/media-proxy";

/** Byte ranges of one stream, streamed through from the internal API. */
export const Route = createFileRoute("/videos/$videoId/media/$itag")({
  server: {
    handlers: {
      GET: ({ request, params }) => {
        if (!isVideoId(params.videoId) || !isFormatId(params.itag)) {
          return notFound();
        }
        return proxyToApi(
          request,
          `/videos/${params.videoId}/media/${params.itag}`,
        );
      },
    },
  },
});
