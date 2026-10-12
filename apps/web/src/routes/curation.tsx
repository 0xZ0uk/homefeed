import { Link, createFileRoute } from "@tanstack/react-router";

import { ChannelsTab } from "#/components/ChannelsTab";
import { LogoutButton } from "#/components/LogoutButton";
import { MutesTab } from "#/components/MutesTab";
import { TopicsTab } from "#/components/TopicsTab";
import { channelsQuery } from "#/server/channels";
import { displayPrefsQuery } from "#/server/display";
import { keywordMutesQuery } from "#/server/keyword-mutes";
import { topicsQuery } from "#/server/topics";

// Searches and sources tabs arrive in later milestones.
const TABS = [
  { id: "channels", label: "Channels" },
  { id: "topics", label: "Topics" },
  { id: "mutes", label: "Mutes" },
] as const;
type Tab = (typeof TABS)[number]["id"];

interface CurationSearch {
  tab?: Tab;
}

export const Route = createFileRoute("/curation")({
  validateSearch: (search: Record<string, unknown>): CurationSearch => ({
    tab: TABS.some((t) => t.id === search.tab)
      ? (search.tab as Tab)
      : undefined,
  }),
  head: () => ({ meta: [{ title: "Curation · Homefeed" }] }),
  loaderDeps: ({ search }) => ({ tab: search.tab ?? "channels" }),
  loader: async ({ context, deps }) => {
    // Only the open tab's data; the other loads when its tab is opened.
    if (deps.tab === "mutes") {
      await context.queryClient.ensureQueryData(keywordMutesQuery);
    } else if (deps.tab === "topics") {
      await context.queryClient.ensureQueryData(topicsQuery);
    } else {
      await Promise.all([
        context.queryClient.ensureQueryData(channelsQuery),
        context.queryClient.ensureQueryData(displayPrefsQuery),
      ]);
    }
  },
  component: Curation,
});

function Curation() {
  const { tab = "channels" } = Route.useSearch();

  return (
    <main className="mx-auto max-w-3xl p-8">
      <header className="flex items-baseline justify-between gap-4">
        <h1 className="text-3xl font-bold">Curation</h1>
        <nav className="flex items-baseline gap-4">
          <Link to="/" className="underline">
            Home
          </Link>
          <LogoutButton />
        </nav>
      </header>
      <nav aria-label="Curation sections" className="mt-6 flex gap-2 border-b">
        {TABS.map((t) => (
          <Link
            key={t.id}
            to="/curation"
            search={{ tab: t.id }}
            aria-current={t.id === tab ? "page" : undefined}
            className="-mb-px border-b-2 border-transparent px-3 py-2 aria-[current=page]:border-black aria-[current=page]:font-medium"
          >
            {t.label}
          </Link>
        ))}
      </nav>
      <section className="mt-6">
        {tab === "channels" && <ChannelsTab />}
        {tab === "topics" && <TopicsTab />}
        {tab === "mutes" && <MutesTab />}
      </section>
    </main>
  );
}
