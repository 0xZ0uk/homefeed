import {
  Link,
  useLocation,
  useMatch,
  useNavigate,
} from "@tanstack/react-router";
import { Menu, Search } from "lucide-react";
import {
  useState,
  useSyncExternalStore,
  type FormEvent,
  type ReactNode,
} from "react";

import { AccountMenu } from "#/components/AccountMenu";
import { QueueSheet, openQueue } from "#/components/QueueSheet";
import { Button } from "#/components/ui/button";
import { Input } from "#/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "#/components/ui/sheet";
import {
  DESTINATIONS,
  locateNav,
  type NavDestination,
  type NavPage,
  type NavSpot,
} from "#/lib/nav";
import { cn } from "#/lib/utils";

// Whether the docked guide is full width or the mini rail. Every page renders
// its own shell, so this lives outside React to survive navigation.
let guideExpanded = true;
const guideListeners = new Set<() => void>();
const guideStore = {
  subscribe(listener: () => void) {
    guideListeners.add(listener);
    return () => guideListeners.delete(listener);
  },
  get: () => guideExpanded,
  toggle() {
    guideExpanded = !guideExpanded;
    for (const listener of guideListeners) listener();
  },
};

/**
 * Every signed-in page's frame: a masthead with the menu button, logo, search
 * box, the page's own `actions`, the queue and the account menu; the guide (the
 * main navigation, four destinations) down the left; and the page itself in
 * `<main>`. On wide screens the guide is docked and the menu button switches it
 * between full width and a mini rail; on narrow screens, or with
 * `guide="drawer"` (the watch page), it opens as a drawer instead.
 *
 * The first stop for Tab is "Skip to content", and `<main>` takes focus when
 * you navigate to another page (see `NavigationFocus`). The page puts its title
 * in an `<h1>`.
 */
export function AppShell({
  children,
  className,
  actions,
  guide = "docked",
}: {
  children: ReactNode;
  /** Page-specific controls for the masthead, shown before the queue. */
  actions?: ReactNode;
  /** Classes for the `<main>` element, e.g. its max width. */
  className?: string;
  guide?: "docked" | "drawer";
}) {
  const expanded = useSyncExternalStore(
    guideStore.subscribe,
    guideStore.get,
    () => true,
  );
  const [drawerOpen, setDrawerOpen] = useState(false);
  const docked = guide === "docked";

  function onMenu() {
    if (docked && window.matchMedia("(min-width: 64rem)").matches) {
      guideStore.toggle();
    } else {
      setDrawerOpen(true);
    }
  }

  return (
    <div className="min-h-svh">
      <SkipLink />
      {/* Equal outer columns keep the search box centred on the screen, not
          in whatever space the logo and the page's actions leave. */}
      <header className="sticky top-0 z-40 grid h-14 grid-cols-[1fr_auto] items-center gap-4 bg-background px-2 sm:grid-cols-[1fr_minmax(0,36rem)_1fr] sm:px-4">
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon-lg"
            aria-label="Menu"
            aria-expanded={docked ? undefined : drawerOpen}
            onClick={onMenu}
          >
            <Menu className="size-5" />
          </Button>
          <Logo />
        </div>
        <MastheadSearch />
        <div className="flex items-center justify-end gap-1 sm:col-start-3">
          <Button
            variant="ghost"
            size="icon-lg"
            aria-label="Search"
            className="sm:hidden"
            nativeButton={false}
            render={<Link to="/search" />}
          >
            <Search className="size-5" />
          </Button>
          {actions}
          <QueueSheet />
          <AccountMenu />
        </div>
      </header>

      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent
          side="left"
          showCloseButton={false}
          className="w-60 gap-0 border-transparent bg-background p-0 data-[side=left]:w-60"
        >
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SheetDescription className="sr-only">
            Go to another page.
          </SheetDescription>
          <div className="flex h-14 shrink-0 items-center gap-1 px-2 sm:px-4">
            <Button
              variant="ghost"
              size="icon-lg"
              aria-label="Close menu"
              onClick={() => setDrawerOpen(false)}
            >
              <Menu className="size-5" />
            </Button>
            <Logo />
          </div>
          <Guide onNavigate={() => setDrawerOpen(false)} />
        </SheetContent>
      </Sheet>

      <div className="flex">
        {docked && (
          <aside
            className={cn(
              "sticky top-14 hidden h-[calc(100svh-3.5rem)] shrink-0 overflow-y-auto overscroll-contain lg:block",
              expanded ? "w-60" : "w-[4.5rem]",
            )}
          >
            {expanded ? <Guide /> : <MiniGuide />}
          </aside>
        )}
        <main
          id="main"
          tabIndex={-1}
          className={cn(
            "mx-auto w-full min-w-0 flex-1 px-4 pt-2 pb-16 outline-none sm:px-6",
            className,
          )}
        >
          {children}
        </main>
      </div>
    </div>
  );
}

/**
 * "Skip to content": the first stop for Tab. It waits just above the viewport
 * and slides into view when it has focus. It moves focus to `<main>` without
 * adding `#main` to the address.
 */
function SkipLink() {
  return (
    <a
      href="#main"
      onClick={(event) => {
        event.preventDefault();
        document.getElementById("main")?.focus();
      }}
      className="fixed top-2 left-2 z-50 -translate-y-[calc(100%+1rem)] rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground outline-none focus:translate-y-0 focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      Skip to content
    </a>
  );
}

function Logo() {
  return (
    <Link
      to="/"
      className="flex items-center gap-1 rounded-lg px-2 py-1.5 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      <span
        aria-hidden="true"
        className="flex h-5 w-7 items-center justify-center rounded-[0.35rem] bg-brand"
      >
        <span className="ml-0.5 size-0 border-y-[0.3rem] border-l-[0.5rem] border-y-transparent border-l-white" />
      </span>
      {/* The name stays for screen readers where the masthead has no room. */}
      <span className="text-lg font-semibold tracking-tighter max-[24rem]:sr-only">
        Homefeed
      </span>
    </Link>
  );
}

/** YouTube's search box: a pill field joined to a search button, showing the
 * query on the search page. Hidden on narrow screens, where the masthead
 * links to the search page instead. */
function MastheadSearch() {
  const query = useMatch({ from: "/search", shouldThrow: false })?.search.q;
  // Remount when the query changes, so the field shows the current search.
  return <MastheadSearchForm key={query} query={query ?? ""} />;
}

function MastheadSearchForm({ query }: { query: string }) {
  const navigate = useNavigate();
  const [q, setQ] = useState(query);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = q.trim();
    if (query) void navigate({ to: "/search", search: { q: query } });
  }

  return (
    <form
      role="search"
      onSubmit={onSubmit}
      action="/search"
      className="hidden w-full min-w-0 sm:flex"
    >
      <Input
        type="search"
        name="q"
        value={q}
        onChange={(event) => setQ(event.target.value)}
        placeholder="Search YouTube"
        aria-label="Search YouTube"
        className="h-10 rounded-l-full rounded-r-none bg-transparent pl-4 md:text-base dark:bg-transparent"
      />
      <Button
        type="submit"
        variant="secondary"
        aria-label="Search"
        className="h-10 w-16 rounded-l-none rounded-r-full border border-l-0 border-input"
      >
        <Search className="size-5" />
      </Button>
    </form>
  );
}

/** What `aria-current` says about a destination: "page" on its own page (the
 * hub, or Today's feed), "true" when you're on one of its pages. */
function currentOf(
  destination: NavDestination,
  spot: NavSpot | null,
): "page" | "true" | undefined {
  if (spot?.destination !== destination) return undefined;
  return spot.atDestination ? "page" : "true";
}

/** The full-width guide: the four destinations, and under the one you're in,
 * the pages that belong to it. */
function Guide({ onNavigate }: { onNavigate?: () => void }) {
  const { pathname, search } = useLocation();
  const spot = locateNav(pathname, search);

  return (
    <nav aria-label="Main" className="px-3 pb-6">
      <ul className="flex flex-col">
        {DESTINATIONS.map((destination) => {
          const { label, to, icon: Icon, pages } = destination;
          const current = currentOf(destination, spot);
          return (
            <li key={to}>
              <Link
                to={to}
                activeOptions={{ exact: true }}
                aria-current={current}
                onClick={onNavigate}
                className="group flex h-10 items-center gap-6 rounded-lg px-3 text-sm outline-none hover:bg-secondary focus-visible:ring-3 focus-visible:ring-ring/50 aria-[current=page]:bg-secondary aria-[current]:font-medium"
              >
                <Icon className="size-5 shrink-0 group-aria-[current]:stroke-[2.5]" />
                {label}
              </Link>
              {current && pages.length > 0 && (
                <ul aria-label={`In ${label}`} className="flex flex-col">
                  {pages.map((page) => (
                    <li key={page.label}>
                      <PageLink
                        page={page}
                        current={spot?.page === page}
                        onNavigate={onNavigate}
                      />
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** One of a destination's pages in the guide, indented under its label. The
 * queue isn't a page: its entry opens the queue sheet. */
function PageLink({
  page,
  current,
  onNavigate,
}: {
  page: NavPage;
  current: boolean;
  onNavigate?: () => void;
}) {
  const className =
    "flex h-9 w-full items-center rounded-lg pr-3 pl-14 text-left text-sm text-muted-foreground outline-none hover:bg-secondary hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 aria-[current=page]:bg-secondary aria-[current=page]:font-medium aria-[current=page]:text-foreground";

  if ("opens" in page) {
    return (
      <button
        type="button"
        aria-haspopup="dialog"
        onClick={() => {
          onNavigate?.();
          openQueue();
        }}
        className={className}
      >
        {page.label}
      </button>
    );
  }
  return (
    <Link
      to={page.to}
      search={page.search}
      aria-current={current ? "page" : undefined}
      onClick={onNavigate}
      className={className}
    >
      {page.label}
    </Link>
  );
}

/** The collapsed guide: the four destinations as an icon over a small label. */
function MiniGuide() {
  const { pathname, search } = useLocation();
  const spot = locateNav(pathname, search);

  return (
    <nav aria-label="Main" className="px-1 pt-1">
      <ul className="flex flex-col gap-1">
        {DESTINATIONS.map((destination) => {
          const { label, to, icon: Icon } = destination;
          return (
            <li key={to}>
              <Link
                to={to}
                activeOptions={{ exact: true }}
                aria-current={currentOf(destination, spot)}
                className="group flex flex-col items-center gap-1.5 rounded-lg py-3 text-xs outline-none hover:bg-secondary focus-visible:ring-3 focus-visible:ring-ring/50 aria-[current]:bg-secondary aria-[current]:font-medium"
              >
                <Icon className="size-5 group-aria-[current]:stroke-[2.5]" />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
