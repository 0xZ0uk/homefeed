import { createFileRoute } from "@tanstack/react-router";

import { HubPage } from "#/components/HubPage";
import { YourTags } from "#/components/YourTags";
import { EXPLORE } from "#/lib/nav";

/** Explore: ways to find videos and channels beyond the daily feed, and the
 * tags you follow. */
export const Route = createFileRoute("/explore")({
  head: () => ({ meta: [{ title: "Explore · Homefeed" }] }),
  component: Explore,
});

function Explore() {
  return (
    <HubPage destination={EXPLORE}>
      <YourTags />
    </HubPage>
  );
}
