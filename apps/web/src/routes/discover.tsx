import { useQueryErrorResetBoundary } from "@tanstack/react-query";
import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useEffect } from "react";

import { AppShell } from "#/components/AppShell";
import { SuggestedChannels } from "#/components/SuggestedChannels";
import { suggestedChannelsQuery } from "#/server/discover";

/** Ways to find new channels and videos beyond the daily feed. */
export const Route = createFileRoute("/discover")({
  head: () => ({ meta: [{ title: "Discover · Homefeed" }] }),
  loader: ({ context: { queryClient } }) =>
    Promise.all([queryClient.ensureQueryData(suggestedChannelsQuery)]),
  component: Discover,
  errorComponent: DiscoverError,
});

function Discover() {
  return (
    <AppShell className="flex max-w-4xl flex-col gap-6">
      <h1 className="text-2xl font-bold">Discover</h1>
      <SuggestedChannels />
    </AppShell>
  );
}

function DiscoverError() {
  const router = useRouter();
  const queryErrorResetBoundary = useQueryErrorResetBoundary();

  useEffect(() => {
    queryErrorResetBoundary.reset();
  }, [queryErrorResetBoundary]);

  return (
    <AppShell className="flex max-w-4xl flex-col gap-6">
      <h1 className="text-2xl font-bold">Discover</h1>
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
    </AppShell>
  );
}
