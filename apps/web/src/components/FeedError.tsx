import { useQueryErrorResetBoundary } from "@tanstack/react-query";
import { useRouter } from "@tanstack/react-router";
import { useEffect } from "react";

import { AppShell } from "#/components/AppShell";
import { Button } from "#/components/ui/button";

/** Shown when a feed page can't load, keeping navigation and log out reachable. */
export function FeedError() {
  const router = useRouter();
  const queryErrorResetBoundary = useQueryErrorResetBoundary();

  useEffect(() => {
    queryErrorResetBoundary.reset();
  }, [queryErrorResetBoundary]);

  return (
    <AppShell className="max-w-4xl">
      <div role="alert" className="mt-8 flex flex-col items-start gap-3">
        <p>Couldn't load the feed. The API may be down.</p>
        <Button variant="secondary" onClick={() => void router.invalidate()}>
          Try again
        </Button>
      </div>
    </AppShell>
  );
}
