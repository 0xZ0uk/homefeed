import type { Page } from "@playwright/test";

import { DISCOVERY, OUTSIDE, seedOutside } from "./cards";
import { API_URL } from "./env";
import {
  BIRDWATCHING,
  WOODWORKING,
  apiGet,
  expect,
  feedItem,
  feedList,
  open,
  test,
  withTail,
} from "./fixtures";

/** One lane of today's feed, by its heading ("New to you, 1 video"). */
function lane(page: Page, title: "New to you" | "From your channels") {
  return page.getByRole("region", {
    name: new RegExp(`^${title} ?, \\d+ videos?$`),
  });
}

/** The bar of chips that narrows both lanes. */
function filters(page: Page) {
  return page.getByRole("group", { name: "Filter by intent" });
}

test("today's feed is two lanes, with Discovery on top of the new one", async ({
  page,
  request,
}) => {
  await seedOutside(request);
  await open(page, "/");

  // Each lane is a section with its own heading, and says how many it holds.
  await expect(
    page.getByRole("heading", {
      level: 2,
      name: withTail("New to you", "1 video"),
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      level: 2,
      name: withTail("From your channels", "4 videos"),
    }),
  ).toBeVisible();
  const fresh = lane(page, "New to you");
  const own = lane(page, "From your channels");
  await expect(
    fresh.getByRole("list", { name: "New to you" }).getByRole("listitem"),
  ).toHaveCount(1);
  await expect(
    fresh.getByRole("list", { name: "New to you" }).getByRole("listitem"),
  ).toContainText(OUTSIDE.title);
  for (const { title } of [...WOODWORKING.videos, ...BIRDWATCHING.videos]) {
    await expect(
      own.getByRole("link", { name: title, exact: true }),
    ).toBeVisible();
    await expect(
      fresh.getByRole("link", { name: title, exact: true }),
    ).toHaveCount(0);
  }

  // The carousel is at the top of the new lane, under its heading, not in the other.
  const discovery = fresh.getByRole("list", { name: "Discovery videos" });
  await expect(discovery).toContainText(DISCOVERY.title);
  await expect(
    fresh.getByRole("heading", { level: 3, name: "Discovery" }),
  ).toBeVisible();
  await expect(own.getByRole("list", { name: "Discovery videos" })).toHaveCount(
    0,
  );
  const [laneTop, shelfTop, gridTop] = await Promise.all([
    fresh.getByRole("heading", { level: 2 }).boundingBox(),
    discovery.boundingBox(),
    fresh.getByRole("list", { name: "New to you" }).boundingBox(),
  ]);
  expect(laneTop!.y).toBeLessThan(shelfTop!.y);
  expect(shelfTop!.y).toBeLessThan(gridTop!.y);

  // "Show more" stays at the end of the page, after both lanes.
  const more = page.getByRole("button", { name: "Show more" });
  const [ownBox, moreBox] = await Promise.all([
    own.boundingBox(),
    more.boundingBox(),
  ]);
  expect(moreBox!.y).toBeGreaterThan(ownBox!.y + ownBox!.height - 1);
});

test("a lane with nothing to show says why", async ({ page }) => {
  await open(page, "/");

  // Every pick comes from a channel followed, so nothing is new.
  await expect(
    page.getByRole("heading", {
      level: 2,
      name: withTail("New to you", "0 videos"),
    }),
  ).toBeVisible();
  await expect(lane(page, "New to you")).toContainText(
    "Today's feed has no picks from channels you don't follow.",
  );
  await expect(
    lane(page, "New to you").getByRole("list", { name: "New to you" }),
  ).toHaveCount(0);
  await expect(
    lane(page, "From your channels").getByRole("listitem"),
  ).toHaveCount(4);
});

test("one bar of chips narrows both lanes by intent", async ({
  page,
  request,
}) => {
  await seedOutside(request);
  // A short video, and a long one that the LLM hasn't scored yet.
  for (const [video_id, seconds] of [
    [BIRDWATCHING.videos[0].id, 300],
    [BIRDWATCHING.videos[1].id, 2400],
  ] as const) {
    const response = await request.post(`${API_URL}/__e2e__/duration`, {
      data: { video_id, seconds },
    });
    expect(response.ok()).toBe(true);
  }
  await open(page, "/");
  const bar = filters(page);
  await expect(bar.getByRole("button")).toHaveText([
    "All",
    "New to me",
    "Quick",
    "10–30 min",
    "Deep dives",
  ]);
  await expect(bar.getByRole("button", { name: "All" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  /** The titles of the cards in both lanes, in alphabetical order. */
  const shown = async () =>
    (
      await feedList(page)
        .getByRole("listitem")
        .evaluateAll((items) =>
          items.map((item) => item.querySelector("h3")?.textContent ?? ""),
        )
    ).sort();
  const everything = [
    ...WOODWORKING.videos.map((v) => v.title),
    ...BIRDWATCHING.videos.map((v) => v.title),
    OUTSIDE.title,
  ].sort();
  expect(await shown()).toEqual(everything);

  // New to me: the video of a channel I don't follow; nothing in the other lane.
  await bar.getByRole("button", { name: "New to me" }).click();
  await expect(bar.getByRole("button", { name: "New to me" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(bar.getByRole("button", { name: "All" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  expect(await shown()).toEqual([OUTSIDE.title]);
  await expect(
    page.getByRole("heading", {
      level: 2,
      name: withTail("From your channels", "0 videos"),
    }),
  ).toBeVisible();
  await expect(lane(page, "From your channels")).toContainText(
    "Nothing here matches “New to me”. Choose All to see the rest.",
  );

  // Quick: under ten minutes.
  await bar.getByRole("button", { name: "Quick" }).click();
  expect(await shown()).toEqual([BIRDWATCHING.videos[0].title]);
  await expect(lane(page, "New to you")).toContainText(
    "Nothing here matches “Quick”.",
  );

  // 10–30 min: the Woodworking videos, not the short or the long ones.
  await bar.getByRole("button", { name: "10–30 min" }).click();
  expect(await shown()).toEqual(WOODWORKING.videos.map((v) => v.title).sort());

  // Deep dives: the one the LLM scored as deep, and the long one it hasn't
  // scored. The outside video is over an hour, but the LLM found it shallow.
  await bar.getByRole("button", { name: "Deep dives" }).click();
  expect(await shown()).toEqual(
    [WOODWORKING.videos[1].title, BIRDWATCHING.videos[1].title].sort(),
  );

  // All brings everything back, and the sort menu is still there.
  await bar.getByRole("button", { name: "All" }).click();
  expect(await shown()).toEqual(everything);
  await expect(page.getByRole("button", { name: /^Sort: / })).toBeVisible();
});

test("the bar stays under the masthead while the page scrolls", async ({
  page,
  request,
}) => {
  await seedOutside(request);
  await open(page, "/");

  const bar = page.locator("[data-sticky-chips]");
  await expect(bar).toHaveCount(1);
  await expect(
    bar.getByRole("group", { name: "Filter by intent" }),
  ).toBeVisible();
  await page.mouse.wheel(0, 900);
  // It stops under the masthead (3.5rem) instead of scrolling away.
  await expect
    .poll(async () => Math.round((await bar.boundingBox())?.y ?? -1))
    .toBe(56);
  await expect(
    filters(page).getByRole("button", { name: "Quick" }),
  ).toBeInViewport();
});

test("a past feed has the same two lanes, without the carousel", async ({
  page,
  request,
}) => {
  await seedOutside(request);
  const { body } = await apiGet<{ date: string }[]>(request, "/feeds");
  await open(page, `/feed/${body[0]!.date}`);

  await expect(
    page.getByRole("heading", {
      level: 2,
      name: withTail("New to you", "1 video"),
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      level: 2,
      name: withTail("From your channels", "4 videos"),
    }),
  ).toBeVisible();
  await expect(feedItem(page, OUTSIDE.title)).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Discovery videos" }),
  ).toHaveCount(0);
  await expect(
    filters(page).getByRole("button", { name: "Deep dives" }),
  ).toBeVisible();
  // Nothing is added to a past feed, and nothing ends it.
  await expect(page.getByRole("button", { name: "Show more" })).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "That's today." }),
  ).toHaveCount(0);
});
