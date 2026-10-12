import { Link } from "@tanstack/react-router";

import { LogoutButton } from "#/components/LogoutButton";

/** Site title and the links every page needs: home, curation, models and log out. */
export function AppHeader({ title = "Homefeed" }: { title?: string }) {
  return (
    <header className="flex flex-wrap items-baseline justify-between gap-4">
      <h1 className="text-3xl font-bold">{title}</h1>
      <nav aria-label="Main" className="flex items-baseline gap-4">
        <Link
          to="/"
          activeOptions={{ exact: true }}
          className="underline aria-[current=page]:font-medium aria-[current=page]:no-underline"
        >
          Today
        </Link>
        <Link
          to="/curation"
          className="underline aria-[current=page]:font-medium aria-[current=page]:no-underline"
        >
          Curation
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
        <LogoutButton />
      </nav>
    </header>
  );
}
