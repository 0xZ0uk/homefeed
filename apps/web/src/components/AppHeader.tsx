import { Link } from "@tanstack/react-router";

import { LogoutButton } from "#/components/LogoutButton";

/** Site title and the links every page needs: home, queue, search, history,
 * playlists, curation, discover, insights, models, settings, status and log out. */
export function AppHeader({ title = "Homefeed" }: { title?: string }) {
  return (
    <header className="flex flex-wrap items-baseline justify-between gap-4">
      <h1 className="text-3xl font-bold">{title}</h1>
      <nav
        aria-label="Main"
        className="flex flex-wrap items-baseline gap-x-4 gap-y-1"
      >
        <Link
          to="/"
          activeOptions={{ exact: true }}
          className="underline aria-[current=page]:font-medium aria-[current=page]:no-underline"
        >
          Today
        </Link>
        <Link
          to="/queue"
          className="underline aria-[current=page]:font-medium aria-[current=page]:no-underline"
        >
          Queue
        </Link>
        <Link
          to="/search"
          className="underline aria-[current=page]:font-medium aria-[current=page]:no-underline"
        >
          Search
        </Link>
        <Link
          to="/history"
          className="underline aria-[current=page]:font-medium aria-[current=page]:no-underline"
        >
          History
        </Link>
        <Link
          to="/playlists"
          className="underline aria-[current=page]:font-medium aria-[current=page]:no-underline"
        >
          Playlists
        </Link>
        <Link
          to="/curation"
          className="underline aria-[current=page]:font-medium aria-[current=page]:no-underline"
        >
          Curation
        </Link>
        <Link
          to="/discover"
          className="underline aria-[current=page]:font-medium aria-[current=page]:no-underline"
        >
          Discover
        </Link>
        <Link
          to="/insights"
          className="underline aria-[current=page]:font-medium aria-[current=page]:no-underline"
        >
          Insights
        </Link>
        <Link
          to="/models"
          className="underline aria-[current=page]:font-medium aria-[current=page]:no-underline"
        >
          Models
        </Link>
        <Link
          to="/settings"
          className="underline aria-[current=page]:font-medium aria-[current=page]:no-underline"
        >
          Settings
        </Link>
        <Link
          to="/status"
          className="underline aria-[current=page]:font-medium aria-[current=page]:no-underline"
        >
          Status
        </Link>
        <LogoutButton />
      </nav>
    </header>
  );
}
