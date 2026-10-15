import type { LinkProps } from "@tanstack/react-router";
import {
  Activity,
  Bookmark,
  ChartLine,
  Compass,
  Cpu,
  Heart,
  History,
  House,
  Library,
  ListVideo,
  Rss,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  SquarePlay,
  UserRound,
  type LucideIcon,
} from "lucide-react";

/**
 * The app's navigation, in one place: four destinations, each with the pages
 * that belong to it. The guide, the mini rail, the drawer and the hub pages
 * (`/explore`, `/library`, `/you`) all read this list, so a new page is one
 * entry in its destination's `pages`:
 *
 *   { label: "Taste", description: "…", icon: Heart, to: "/taste" },
 *
 * and it shows up as a card on the hub, as a link in the guide while you're in
 * that destination, and marks the destination when you're on the page.
 */

/** Where a page in the guide goes. */
type NavTarget =
  | {
      to: NonNullable<LinkProps["to"]>;
      /** Search params that tell this page from others on the same route. */
      search?: Record<string, string>;
    }
  /** Not a page: opens the queue sheet where you are. */
  | { opens: "queue" };

export type NavPage = {
  label: string;
  /** One line on what the page is for, shown on the hub's card. */
  description: string;
  icon: LucideIcon;
} & NavTarget;

export interface NavDestination {
  label: string;
  /** The destination's own page: a hub listing its pages, or Today's feed. */
  to: "/" | "/explore" | "/library" | "/you";
  icon: LucideIcon;
  /** One sentence on what the area is for, at the top of the hub. */
  description?: string;
  pages: NavPage[];
  /** Further paths that belong here without a page of their own, e.g. a tag's
   * page under Explore. */
  also?: string[];
}

export const TODAY: NavDestination = {
  label: "Today",
  to: "/",
  icon: House,
  pages: [],
  // Earlier days' feeds.
  also: ["/feed"],
};

export const EXPLORE: NavDestination = {
  label: "Explore",
  to: "/explore",
  icon: Compass,
  description: "Find videos and channels beyond the ones you already follow.",
  pages: [
    {
      label: "Discover",
      description: "Channels recommended by the channels you follow.",
      icon: Sparkles,
      to: "/discover",
    },
    {
      label: "Search",
      description:
        "Look up any video on YouTube, then queue it or save the search.",
      icon: Search,
      to: "/search",
    },
    {
      label: "Saved searches",
      description:
        "Searches that run with each feed build and add their best results to your picks.",
      icon: Bookmark,
      to: "/subscriptions",
      search: { tab: "searches" },
    },
    {
      label: "Sources",
      description:
        "Subreddits, feeds and pages whose YouTube links join your candidates.",
      icon: Rss,
      to: "/subscriptions",
      search: { tab: "sources" },
    },
  ],
  // The tags you follow or mute are listed on the hub itself.
  also: ["/tags"],
};

export const LIBRARY: NavDestination = {
  label: "Library",
  to: "/library",
  icon: Library,
  description: "Everything you've watched, saved or lined up to watch.",
  pages: [
    {
      label: "History",
      description: "Videos you've watched, newest first, with your ratings.",
      icon: History,
      to: "/history",
    },
    {
      label: "Playlists",
      description: "Lists you've made to watch on purpose.",
      icon: SquarePlay,
      to: "/playlists",
    },
    {
      label: "Queue",
      description: "Videos lined up to watch next.",
      icon: ListVideo,
      opens: "queue",
    },
  ],
};

export const YOU: NavDestination = {
  label: "You",
  to: "/you",
  icon: UserRound,
  description:
    "The channels you follow, what your ratings have taught the feed, and the settings behind it.",
  pages: [
    {
      label: "Subscriptions",
      description:
        "The channels, tags and mutes that shape what the feed picks.",
      icon: SlidersHorizontal,
      to: "/subscriptions",
    },
    {
      label: "Taste",
      description:
        "What the feed believes about you, from your topics, channels and ratings, and how to change it.",
      icon: Heart,
      to: "/taste",
    },
    {
      label: "Insights",
      description: "Whether the feed is working: your good rate, week by week.",
      icon: ChartLine,
      to: "/insights",
    },
    {
      label: "Models",
      description:
        "The ranking models trained on your ratings, and which one is active.",
      icon: Cpu,
      to: "/models",
    },
    {
      label: "Settings",
      description: "Feed size, schedule, tagging, imports and exports.",
      icon: Settings,
      to: "/settings",
    },
    {
      label: "Status",
      description: "How requests to YouTube are going, and what failed lately.",
      icon: Activity,
      to: "/status",
    },
  ],
};

/** The destinations, in the order the guide lists them. */
export const DESTINATIONS: readonly NavDestination[] = [
  TODAY,
  EXPLORE,
  LIBRARY,
  YOU,
];

/** Where in the navigation a page sits. */
export interface NavSpot {
  destination: NavDestination;
  /** The destination's page being viewed, or null on the hub (or a path that
   * belongs to the destination without being one of its pages). */
  page: NavPage | null;
  /** Whether this is the destination's own page: its hub, or Today's feed. */
  atDestination: boolean;
}

/** Whether `pathname` is `base` or inside it: "/tags/x" is in "/tags"; "/tagsy"
 * isn't. The root only matches itself. */
function isWithin(pathname: string, base: string): boolean {
  if (base === "/") return pathname === "/";
  return pathname === base || pathname.startsWith(`${base}/`);
}

function matchesSearch(
  search: Readonly<Record<string, unknown>>,
  wanted: Readonly<Record<string, string>> | undefined,
): boolean {
  return Object.entries(wanted ?? {}).every(
    ([key, value]) =>
      search[key] !== undefined && String(search[key]) === value,
  );
}

/**
 * Which destination (and page) a location belongs to, or null for pages that
 * sit outside the navigation, like a video or a channel. The same route can
 * belong to two destinations: `/subscriptions?tab=searches` is Explore's Saved
 * searches, while the rest of Subscriptions is under You. The most specific
 * match wins: the longest path, then the most search params.
 */
export function locateNav(
  pathname: string,
  search: Readonly<Record<string, unknown>> = {},
): NavSpot | null {
  const matches: { spot: NavSpot; weight: number }[] = [];

  for (const destination of DESTINATIONS) {
    if (pathname === destination.to) {
      matches.push({
        spot: { destination, page: null, atDestination: true },
        weight: pathname.length * 10,
      });
    }
    for (const base of destination.also ?? []) {
      if (!isWithin(pathname, base)) continue;
      matches.push({
        spot: { destination, page: null, atDestination: false },
        weight: base.length * 10,
      });
    }
    for (const page of destination.pages) {
      if (!("to" in page)) continue;
      if (!isWithin(pathname, page.to) || !matchesSearch(search, page.search)) {
        continue;
      }
      matches.push({
        spot: { destination, page, atDestination: false },
        weight: page.to.length * 10 + Object.keys(page.search ?? {}).length,
      });
    }
  }

  matches.sort((a, b) => b.weight - a.weight);
  return matches[0]?.spot ?? null;
}
