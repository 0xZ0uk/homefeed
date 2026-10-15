import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { AppShell } from "#/components/AppShell";
import { openQueue } from "#/components/QueueSheet";
import type { NavDestination, NavPage } from "#/lib/nav";

/**
 * A destination's own page (Explore, Library, You): what the area is for, and
 * its pages as large cards. `counts` adds a figure to a card, by the page's
 * label, where a query the app already makes can supply one; `children` follow
 * the cards.
 */
export function HubPage({
  destination,
  counts = {},
  children,
}: {
  destination: NavDestination;
  counts?: Readonly<Record<string, string | undefined>>;
  children?: ReactNode;
}) {
  return (
    <AppShell className="flex max-w-4xl flex-col gap-8">
      <header className="flex flex-col gap-1 pt-2">
        <h1 className="text-xl font-semibold">{destination.label}</h1>
        {destination.description && (
          <p className="max-w-prose text-pretty text-muted-foreground">
            {destination.description}
          </p>
        )}
      </header>
      <ul
        aria-label={`${destination.label} pages`}
        className="grid gap-3 sm:grid-cols-2"
      >
        {destination.pages.map((page) => (
          <li key={page.label}>
            <HubCard page={page} count={counts[page.label]} />
          </li>
        ))}
      </ul>
      {children}
    </AppShell>
  );
}

/**
 * One page as a card: icon, name, a line on what it's for and, where there is
 * one, a count. The name is the card's one link (or button, for the queue),
 * stretched over the whole card; the rest is plain text beside it.
 */
function HubCard({ page, count }: { page: NavPage; count?: string }) {
  const Icon = page.icon;
  const stretched =
    "rounded-lg text-left outline-none after:absolute after:inset-0 after:rounded-xl focus-visible:after:ring-3 focus-visible:after:ring-ring/50";

  return (
    <div className="group/card relative flex h-full items-start gap-4 rounded-xl border p-5 transition-colors hover:bg-secondary">
      <span
        aria-hidden="true"
        className="flex size-11 shrink-0 items-center justify-center rounded-full bg-secondary transition-colors group-hover/card:bg-background"
      >
        <Icon className="size-5" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-lg leading-snug font-medium">
            {"opens" in page ? (
              <button
                type="button"
                aria-haspopup="dialog"
                onClick={openQueue}
                className={stretched}
              >
                {page.label}
              </button>
            ) : (
              <Link to={page.to} search={page.search} className={stretched}>
                {page.label}
              </Link>
            )}
          </h2>
          {count && (
            <span className="shrink-0 text-sm text-muted-foreground tabular-nums">
              {count}
            </span>
          )}
        </div>
        <p className="text-sm text-pretty text-muted-foreground">
          {page.description}
        </p>
      </div>
    </div>
  );
}
