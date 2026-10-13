import { useQueryErrorResetBoundary } from "@tanstack/react-query";
import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useEffect } from "react";

import { AppHeader } from "#/components/AppHeader";
import { SuggestedChannels } from "#/components/SuggestedChannels";
import { suggestedChannelsQuery } from "#/server/discover";
import { displayPrefsQuery } from "#/server/display";

/** Ways to find new channels and videos beyond the daily feed. */
export const Route = createFileRoute("/discover")({
  head: () => ({ meta: [{ title: "Discover · Homefeed" }] }),
  loader: ({ context: { queryClient } }) =>
    Promise.all([
      queryClient.ensureQueryData(suggestedChannelsQuery),
      queryClient.ensureQueryData(displayPrefsQuery),
    ]),
  component: Discover,
  errorComponent: DiscoverError,
});

function Discover() {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <AppHeader />
      <SuggestedChannels />
    </main>
  );
}

function DiscoverError() {
  const router = useRouter();
  const queryErrorResetBoundary = useQueryErrorResetBoundary();

  useEffect(() => {
    queryErrorResetBoundary.reset();
  }, [queryErrorResetBoundary]);

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <AppHeader />
      <div role="alert" className="flex flex-col items-start gap-3">
        <p>Couldn't load suggestions. The API may be down.</p>
        <button
          type="button"
          onClick={() => void router.invalidate()}
          className="underline"
        >
          Try again
        </button>
      </div>
    </main>
  );
}
