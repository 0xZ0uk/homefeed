import { describe, expect, it } from "vitest";

import { DESTINATIONS, EXPLORE, LIBRARY, TODAY, YOU, locateNav } from "./nav";

/** Where `pathname` sits, as "destination" or "destination > page". */
function where(pathname: string, search: Record<string, unknown> = {}) {
  const spot = locateNav(pathname, search);
  if (!spot) return null;
  return spot.page
    ? `${spot.destination.label} > ${spot.page.label}`
    : spot.destination.label;
}

describe("the destinations", () => {
  it("are Today, Explore, Library and You, in that order", () => {
    expect(DESTINATIONS.map((d) => d.label)).toEqual([
      "Today",
      "Explore",
      "Library",
      "You",
    ]);
    expect(DESTINATIONS.map((d) => d.to)).toEqual([
      "/",
      "/explore",
      "/library",
      "/you",
    ]);
  });

  it("list the pages the hubs promise", () => {
    expect(TODAY.pages).toEqual([]);
    expect(EXPLORE.pages.map((p) => p.label)).toEqual([
      "Discover",
      "Search",
      "Saved searches",
      "Sources",
    ]);
    expect(LIBRARY.pages.map((p) => p.label)).toEqual([
      "History",
      "Playlists",
      "Queue",
    ]);
    expect(YOU.pages.map((p) => p.label)).toEqual([
      "Subscriptions",
      "Taste",
      "Insights",
      "Models",
      "Settings",
      "Status",
    ]);
  });

  it("describe every hub and page, with an icon", () => {
    for (const destination of DESTINATIONS.slice(1)) {
      expect(destination.description).toMatch(/\.$/);
      for (const page of destination.pages) {
        expect(page.description).toMatch(/\.$/);
        expect(page.icon).toBeTruthy();
      }
    }
  });

  it("have unique page labels", () => {
    const labels = DESTINATIONS.flatMap((d) => d.pages.map((p) => p.label));
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("open the queue from the Library, not a page", () => {
    const queue = LIBRARY.pages.find((p) => p.label === "Queue");
    expect(queue).toMatchObject({ opens: "queue" });
    expect(queue).not.toHaveProperty("to");
  });
});

describe("locateNav", () => {
  it("finds every page of every destination from its own link", () => {
    // What makes a new entry in a destination's `pages` work with no other change.
    for (const destination of DESTINATIONS) {
      for (const page of destination.pages) {
        if (!("to" in page)) continue;
        const spot = locateNav(page.to, page.search);
        expect(spot?.destination, page.label).toBe(destination);
        expect(spot?.page, page.label).toBe(page);
        expect(spot?.atDestination, page.label).toBe(false);
      }
    }
  });

  it("puts the feeds under Today", () => {
    expect(locateNav("/")).toMatchObject({
      destination: TODAY,
      page: null,
      atDestination: true,
    });
    expect(locateNav("/feed/2026-10-14")).toMatchObject({
      destination: TODAY,
      page: null,
      atDestination: false,
    });
  });

  it("knows each hub as its destination's own page", () => {
    for (const destination of DESTINATIONS.slice(1)) {
      expect(locateNav(destination.to)).toMatchObject({
        destination,
        page: null,
        atDestination: true,
      });
    }
  });

  it("puts a page's subpages under the page", () => {
    expect(where("/playlists")).toBe("Library > Playlists");
    expect(where("/playlists/3")).toBe("Library > Playlists");
    expect(where("/history", { q: "plane" })).toBe("Library > History");
    expect(where("/insights", { weeks: 12 })).toBe("You > Insights");
    expect(where("/taste")).toBe("You > Taste");
  });

  it("puts tags under Explore without making them a page", () => {
    expect(locateNav("/tags/woodworking")).toMatchObject({
      destination: EXPLORE,
      page: null,
      atDestination: false,
    });
    expect(where("/search", { q: "godot" })).toBe("Explore > Search");
  });

  it("tells Subscriptions' tabs apart", () => {
    expect(where("/subscriptions")).toBe("You > Subscriptions");
    expect(where("/subscriptions", { tab: "channels" })).toBe(
      "You > Subscriptions",
    );
    expect(where("/subscriptions", { tab: "tags" })).toBe(
      "You > Subscriptions",
    );
    expect(where("/subscriptions", { tab: "mutes" })).toBe(
      "You > Subscriptions",
    );
    expect(where("/subscriptions", { tab: "searches" })).toBe(
      "Explore > Saved searches",
    );
    expect(where("/subscriptions", { tab: "sources" })).toBe(
      "Explore > Sources",
    );
  });

  it("leaves pages outside the navigation out", () => {
    expect(where("/watch/abc12345678")).toBeNull();
    expect(where("/channels/UC123")).toBeNull();
    expect(where("/welcome")).toBeNull();
    expect(where("/nowhere")).toBeNull();
  });

  it("matches whole path segments only", () => {
    expect(where("/historyx")).toBeNull();
    expect(where("/tagsy")).toBeNull();
    expect(where("/feeds")).toBeNull();
  });
});
