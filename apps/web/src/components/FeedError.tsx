import { useQueryErrorResetBoundary } from "@tanstack/react-query";
import { useRouter } from "@tanstack/react-router";
import { useEffect } from "react";

import { AppHeader } from "#/components/AppHeader";

/** Shown when a feed page can't load, keeping navigation and log out reachable. */
export function FeedError() {
  const router = useRouter();
  const queryErrorResetBoundary = useQueryErrorResetBoundary();

  useEffect(() => {
    queryErrorResetBoundary.reset();
  }, [queryErrorResetBoundary]);

  return (
    <main className="mx-auto max-w-3xl p-8">
      <AppHeader />
      <div role="alert" className="mt-8 flex flex-col items-start gap-3">
        <p>Couldn't load the feed. The API may be down.</p>
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
