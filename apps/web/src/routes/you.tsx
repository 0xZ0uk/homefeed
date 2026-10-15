import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

import { HubPage } from "#/components/HubPage";
import { plural } from "#/lib/insights";
import { YOU } from "#/lib/nav";
import { channelsQuery } from "#/server/channels";

/** You: your subscriptions, what your ratings have taught the feed, and the
 * settings and health of the app behind it. */
export const Route = createFileRoute("/you")({
  head: () => ({ meta: [{ title: "You · Homefeed" }] }),
  component: You,
});

function You() {
  // The count is extra: the page works without it if the API is down.
  const { data: channels } = useQuery(channelsQuery);

  return (
    <HubPage
      destination={YOU}
      counts={{
        Subscriptions: channels && plural(channels.length, "channel"),
      }}
    />
  );
}
