import { Link, useNavigate, type LinkProps } from "@tanstack/react-router";
import {
  Activity,
  ChartLine,
  Compass,
  Cpu,
  History,
  House,
  ListVideo,
  Menu,
  Search,
  Settings,
  SlidersHorizontal,
  SquarePlay,
  type LucideIcon,
} from "lucide-react";
import {
  useState,
  useSyncExternalStore,
  type FormEvent,
  type ReactNode,
} from "react";

import { LogoutButton } from "#/components/LogoutButton";
import { Button } from "#/components/ui/button";
import { Input } from "#/components/ui/input";
import { Separator } from "#/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "#/components/ui/sheet";
import { cn } from "#/lib/utils";

type NavItem = {
  to: LinkProps["to"];
  label: string;
  icon: LucideIcon;
  exact?: boolean;
};

/** The guide's sections, YouTube-style: your stuff, then finding more, then
 * the app itself. */
const NAV: NavItem[][] = [
  [
    { to: "/", label: "Today", icon: House, exact: true },
    { to: "/queue", label: "Queue", icon: ListVideo },
    { to: "/history", label: "History", icon: History },
    { to: "/playlists", label: "Playlists", icon: SquarePlay },
  ],
  [
    { to: "/search", label: "Search", icon: Search },
    { to: "/discover", label: "Discover", icon: Compass },
    { to: "/curation", label: "Curation", icon: SlidersHorizontal },
    { to: "/insights", label: "Insights", icon: ChartLine },
    { to: "/models", label: "Models", icon: Cpu },
  ],
  [
    { to: "/settings", label: "Settings", icon: Settings },
    { to: "/status", label: "Status", icon: Activity },
  ],
];

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
 * Every signed-in page's frame, after YouTube's: a masthead with the menu
 * button, logo, search box and log out, and the guide (the main navigation)
 * down the left. On wide screens the guide is docked and the menu button
 * switches it between full width and a mini rail; on narrow screens, or with
 * `guide="drawer"` (the watch page), it opens as a drawer instead.
 */
export function AppShell({
  children,
  className,
  guide = "docked",
}: {
  children: ReactNode;
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
      <h1 className="sr-only">Homefeed</h1>
      <header className="sticky top-0 z-40 flex h-14 items-center gap-4 bg-background px-2 sm:px-4">
        <div className="flex shrink-0 items-center gap-1">
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
        <div className="ml-auto flex shrink-0 items-center gap-1">
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
          <LogoutButton />
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
          className={cn(
            "mx-auto w-full min-w-0 flex-1 px-4 pt-2 pb-12 sm:px-6",
            className,
          )}
        >
          {children}
        </main>
      </div>
    </div>
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
      <span className="text-lg font-semibold tracking-tighter">Homefeed</span>
    </Link>
  );
}

/** YouTube's search box: a pill field joined to a search button. Hidden on
 * narrow screens, where the masthead links to the search page instead. */
function MastheadSearch() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");

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
      className="mx-auto hidden w-full max-w-xl min-w-0 sm:flex"
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

/** The full-width guide: each section's links with icon and label. */
function Guide({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="flex flex-col px-3 pb-6">
      {NAV.map((section, index) => (
        <div key={index} className="flex flex-col">
          {index > 0 && <Separator className="my-3" />}
          {section.map(({ to, label, icon: Icon, exact }) => (
            <Link
              key={label}
              to={to}
              activeOptions={{ exact }}
              onClick={onNavigate}
              className="group flex h-10 items-center gap-6 rounded-lg px-3 text-sm outline-none hover:bg-secondary focus-visible:ring-3 focus-visible:ring-ring/50 aria-[current=page]:bg-secondary aria-[current=page]:font-medium"
            >
              <Icon className="size-5 shrink-0 group-aria-[current=page]:stroke-[2.5]" />
              {label}
            </Link>
          ))}
        </div>
      ))}
    </nav>
  );
}

/** The collapsed guide: every link as an icon over a tiny label. */
function MiniGuide() {
  return (
    <nav aria-label="Main" className="flex flex-col gap-1 px-1 pt-1">
      {NAV.flat().map(({ to, label, icon: Icon, exact }) => (
        <Link
          key={label}
          to={to}
          activeOptions={{ exact }}
          className="group flex flex-col items-center gap-1.5 rounded-lg py-3 text-[0.625rem] outline-none hover:bg-secondary focus-visible:ring-3 focus-visible:ring-ring/50 aria-[current=page]:font-medium"
        >
          <Icon className="size-5 group-aria-[current=page]:stroke-[2.5]" />
          {label}
        </Link>
      ))}
    </nav>
  );
}
