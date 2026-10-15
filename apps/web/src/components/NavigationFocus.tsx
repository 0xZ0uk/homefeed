import { useRouter } from "@tanstack/react-router";
import { useEffect } from "react";

/**
 * Moves focus to `<main>` when you navigate to another page, so keyboard and
 * screen reader users start at the top of the new page instead of on a link
 * that is gone. Only a different path counts: changing a filter or a tab keeps
 * the same page, and the first load has nothing to move from. Focus doesn't
 * scroll the page, which the router has already positioned.
 *
 * Renders nothing; the root route mounts it once, so it outlives each page's
 * own shell.
 */
export function NavigationFocus() {
  const router = useRouter();

  useEffect(
    () =>
      router.subscribe("onResolved", ({ fromLocation, pathChanged }) => {
        if (!fromLocation || !pathChanged) return;
        document.getElementById("main")?.focus({ preventScroll: true });
      }),
    [router],
  );

  return null;
}
