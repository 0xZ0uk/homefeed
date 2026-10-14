import { createFileRoute, redirect } from "@tanstack/react-router";

// The page was renamed to Subscriptions; keep old links and bookmarks working.
export const Route = createFileRoute("/curation")({
  validateSearch: (search: Record<string, unknown>): { tab?: string } => ({
    tab: typeof search.tab === "string" ? search.tab : undefined,
  }),
  beforeLoad: ({ search }) => {
    throw redirect({
      to: "/subscriptions",
      search: (search.tab ? { tab: search.tab } : {}) as { tab?: never },
      replace: true,
    });
  },
});
