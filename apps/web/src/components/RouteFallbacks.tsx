import { useQueryErrorResetBoundary } from "@tanstack/react-query";
import { Link, useRouter } from "@tanstack/react-router";
import { useEffect } from "react";

import { AppShell } from "#/components/AppShell";
import { Button, buttonVariants } from "#/components/ui/button";

/**
 * The page shown when a route fails to load and has no error view of its own
 * (the router's default): in the app's frame, so there's always a way on. Try
 * again reloads the page's data; the usual cause is the API being down.
 */
export function RouteError() {
  const router = useRouter();
  const queryErrorResetBoundary = useQueryErrorResetBoundary();

  useEffect(() => {
    queryErrorResetBoundary.reset();
  }, [queryErrorResetBoundary]);

  return (
    <AppShell className="flex max-w-4xl flex-col gap-4">
      <h1 className="pt-2 text-xl font-semibold">Something went wrong</h1>
      <div role="alert" className="flex flex-col items-start gap-3">
        <p>Couldn't load this page. The API may be down.</p>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="secondary"
            size="lg"
            className="px-4"
            onClick={() => void router.invalidate()}
          >
            Try again
          </Button>
          <Link
            to="/"
            className={buttonVariants({ variant: "ghost", size: "lg" })}
          >
            Go to Today
          </Link>
        </div>
      </div>
    </AppShell>
  );
}

/** The page shown for an address that doesn't exist (the router's default), in
 * the app's frame, with a way back to the feed. */
export function RouteNotFound() {
  return (
    <AppShell className="flex max-w-4xl flex-col items-start gap-3">
      <h1 className="pt-2 text-xl font-semibold">Page not found</h1>
      <p>This page doesn't exist.</p>
      <Link
        to="/"
        className={buttonVariants({ variant: "secondary", size: "lg" })}
      >
        Go to Today
      </Link>
    </AppShell>
  );
}
