import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

import { HubPage } from "#/components/HubPage";
import { plural } from "#/lib/insights";
import { LIBRARY } from "#/lib/nav";
import { playlistsQuery } from "#/server/playlists";
import { queueQuery } from "#/server/queue";

/** Library: what you've watched, saved in playlists or queued to watch. */
export const Route = createFileRoute("/library")({
  head: () => ({ meta: [{ title: "Library · Homefeed" }] }),
  component: Library,
});

function Library() {
  // Counts are extra: the page works without them if the API is down.
  const { data: playlists } = useQuery(playlistsQuery);
  const { data: queue } = useQuery(queueQuery);

  return (
    <HubPage
      destination={LIBRARY}
      counts={{
        Playlists: playlists && plural(playlists.length, "playlist"),
        Queue: queue && plural(queue.length, "video"),
      }}
    />
  );
}
