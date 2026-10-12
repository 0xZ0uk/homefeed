import { Link, createFileRoute } from "@tanstack/react-router";

import { ChannelsTab } from "#/components/ChannelsTab";
import { LogoutButton } from "#/components/LogoutButton";
import { channelsQuery } from "#/server/channels";

// Topics, mutes, searches and sources tabs arrive in later milestones.
const TABS = [{ id: "channels", label: "Channels" }] as const;
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
  loader: ({ context }) => context.queryClient.ensureQueryData(channelsQuery),
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
      </section>
    </main>
  );
}
