import { Link, createFileRoute } from "@tanstack/react-router";

import { AppShell } from "#/components/AppShell";
import { ChannelsTab } from "#/components/ChannelsTab";
import { MutesTab } from "#/components/MutesTab";
import { SavedSearchesTab } from "#/components/SavedSearchesTab";
import { SourcesTab } from "#/components/SourcesTab";
import { TagsTab } from "#/components/TagsTab";
import { channelsQuery } from "#/server/channels";
import { externalSourcesQuery } from "#/server/external-sources";
import { keywordMutesQuery } from "#/server/keyword-mutes";
import { savedSearchesQuery } from "#/server/saved-searches";
import { tagAdminQuery } from "#/server/tag-admin";

const TABS = [
  { id: "channels", label: "Channels" },
  { id: "tags", label: "Tags" },
  { id: "mutes", label: "Mutes" },
  { id: "searches", label: "Searches" },
  { id: "sources", label: "Sources" },
] as const;
type Tab = (typeof TABS)[number]["id"];

interface SubscriptionsSearch {
  tab?: Tab;
}

export const Route = createFileRoute("/subscriptions")({
  validateSearch: (search: Record<string, unknown>): SubscriptionsSearch => ({
    tab: TABS.some((t) => t.id === search.tab)
      ? (search.tab as Tab)
      : undefined,
  }),
  head: () => ({ meta: [{ title: "Subscriptions · Homefeed" }] }),
  loaderDeps: ({ search }) => ({ tab: search.tab ?? "channels" }),
  loader: async ({ context, deps }) => {
    // Only the open tab's data; the other loads when its tab is opened.
    if (deps.tab === "mutes") {
      await context.queryClient.ensureQueryData(keywordMutesQuery);
    } else if (deps.tab === "tags") {
      await context.queryClient.ensureQueryData(tagAdminQuery(""));
    } else if (deps.tab === "searches") {
      await context.queryClient.ensureQueryData(savedSearchesQuery);
    } else if (deps.tab === "sources") {
      await context.queryClient.ensureQueryData(externalSourcesQuery);
    } else {
      await Promise.all([context.queryClient.ensureQueryData(channelsQuery)]);
    }
  },
  component: Subscriptions,
});

function Subscriptions() {
  const { tab = "channels" } = Route.useSearch();

  return (
    <AppShell className="max-w-4xl">
      <h2 className="text-2xl font-bold">Subscriptions</h2>
      <nav
        aria-label="Subscriptions sections"
        className="mt-4 flex gap-2 overflow-x-auto border-b"
      >
        {TABS.map((t) => (
          <Link
            key={t.id}
            to="/subscriptions"
            search={{ tab: t.id }}
            aria-current={t.id === tab ? "page" : undefined}
            className="-mb-px shrink-0 border-b-2 border-transparent px-3 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground aria-[current=page]:border-foreground aria-[current=page]:text-foreground"
          >
            {t.label}
          </Link>
        ))}
      </nav>
      <section className="mt-6">
        {tab === "channels" && <ChannelsTab />}
        {tab === "tags" && <TagsTab />}
        {tab === "mutes" && <MutesTab />}
        {tab === "searches" && <SavedSearchesTab />}
        {tab === "sources" && <SourcesTab />}
      </section>
    </AppShell>
  );
}
