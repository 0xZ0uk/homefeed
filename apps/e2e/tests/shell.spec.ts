import { cardButton } from "./cards";
import { API_URL } from "./env";
import {
  BIRDWATCHING,
  WOODWORKING,
  expect,
  feedItem,
  open,
  test,
} from "./fixtures";

test("the guide has four destinations, and the one you're in lists its pages", async ({
  page,
}) => {
  await open(page, "/");
  const guide = page.getByRole("navigation", { name: "Main" });
  await expect(guide.getByRole("link")).toHaveText([
    "Today",
    "Explore",
    "Library",
    "You",
  ]);
  await expect(guide.getByRole("link", { name: "Today" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  // A destination's own page is a hub: what the area is for, and its pages.
  await guide.getByRole("link", { name: "Library" }).click();
  await expect(page).toHaveURL("/library");
  await expect(
    page.getByRole("heading", { level: 1, name: "Library" }),
  ).toBeVisible();
  await expect(guide.getByRole("link", { name: "Library" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  const pages = guide.getByRole("list", { name: "In Library" });
  await expect(pages.getByRole("link")).toHaveText(["History", "Playlists"]);
  await expect(pages.getByRole("button", { name: "Queue" })).toBeVisible();
  const cards = page
    .getByRole("main")
    .getByRole("list", { name: "Library pages" });
  await expect(cards.getByRole("heading")).toHaveText([
    "History",
    "Playlists",
    "Queue",
  ]);

  // A page marks its destination, and itself among the destination's pages.
  await cards.getByRole("link", { name: "History" }).click();
  await expect(page).toHaveURL("/history");
  await expect(guide.getByRole("link", { name: "Library" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  await expect(pages.getByRole("link", { name: "History" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(guide.getByRole("list", { name: "In Explore" })).toHaveCount(0);
});

test("Subscriptions' searches and sources tabs belong to Explore", async ({
  page,
}) => {
  const guide = page.getByRole("navigation", { name: "Main" });

  await open(page, "/subscriptions");
  await expect(guide.getByRole("link", { name: "You" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  await expect(
    guide
      .getByRole("list", { name: "In You" })
      .getByRole("link", { name: "Subscriptions" }),
  ).toHaveAttribute("aria-current", "page");

  await open(page, "/subscriptions?tab=searches");
  await expect(guide.getByRole("link", { name: "Explore" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  await expect(
    guide
      .getByRole("list", { name: "In Explore" })
      .getByRole("link", { name: "Saved searches" }),
  ).toHaveAttribute("aria-current", "page");
  await expect(guide.getByRole("list", { name: "In You" })).toHaveCount(0);
});

test("Explore leads to discovery, search, saved searches and sources", async ({
  page,
}) => {
  await open(page, "/explore");

  await expect(
    page.getByRole("heading", { level: 1, name: "Explore" }),
  ).toBeVisible();
  const cards = page.getByRole("main").getByRole("list", {
    name: "Explore pages",
  });
  await expect(cards.getByRole("link")).toHaveText([
    "Discover",
    "Search",
    "Saved searches",
    "Sources",
  ]);
  await cards.getByRole("link", { name: "Sources" }).click();
  await expect(page).toHaveURL("/subscriptions?tab=sources");
});

test("You leads to the subscriptions, taste, insights, models, settings and status", async ({
  page,
}) => {
  await open(page, "/you");

  const cards = page.getByRole("main").getByRole("list", {
    name: "You pages",
  });
  await expect(cards.getByRole("link")).toHaveText([
    "Subscriptions",
    "Taste",
    "Insights",
    "Models",
    "Settings",
    "Status",
  ]);
  // The channels the app already lists give the Subscriptions card its count.
  await expect(cards).toContainText("2 channels");
});

test("Skip to content is the first Tab stop and moves focus to the page", async ({
  page,
}) => {
  await open(page, "/history");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).not.toBeInViewport();

  await page.keyboard.press("Tab");
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport({ ratio: 1 });
  await page.keyboard.press("Enter");

  await expect(page.getByRole("main")).toBeFocused();
  expect(page.url()).not.toContain("#");
  // The next Tab stop is the first control of the page, not the masthead.
  await page.keyboard.press("Tab");
  await expect(page.getByRole("main")).not.toBeFocused();
  expect(
    await page.evaluate(() => document.activeElement?.closest("main") !== null),
  ).toBe(true);
});

test("going to another page moves focus to it; changing a filter doesn't", async ({
  page,
}) => {
  await open(page, "/status");
  const week = page.getByRole("link", { name: "Last 7 days" });
  await week.click();
  await expect(page).toHaveURL("/status?hours=168");
  await expect(week).toHaveAttribute("aria-current", "page");
  // Same page, new window: focus stays on the link that was used.
  await page.waitForTimeout(300);
  await expect(week).toBeFocused();

  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Explore" })
    .click();
  await expect(page).toHaveURL("/explore");
  await expect(page.getByRole("main")).toBeFocused();
});

test("a page chosen in the drawer gets focus, not the menu button", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "/history");

  await page.getByRole("button", { name: "Menu", exact: true }).click();
  await page
    .getByRole("dialog", { name: "Navigation" })
    .getByRole("link", { name: "Explore" })
    .click();

  await expect(page).toHaveURL("/explore");
  await expect(page.getByRole("main")).toBeFocused();
  // Give a late focus return time to show itself.
  await page.waitForTimeout(500);
  await expect(page.getByRole("main")).toBeFocused();
});

test("a page chosen in the drawer with the keyboard gets focus too", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "/history");

  const menu = page.getByRole("button", { name: "Menu", exact: true });
  await menu.focus();
  await page.keyboard.press("Enter");
  const drawer = page.getByRole("dialog", { name: "Navigation" });
  await expect(drawer).toBeVisible();
  await drawer.getByRole("link", { name: "Explore" }).focus();
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL("/explore");
  await page.waitForTimeout(500);
  await expect(page.getByRole("main")).toBeFocused();
});

test("the queue opens from the drawer and keeps focus", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "/library");

  await page.getByRole("button", { name: "Menu", exact: true }).click();
  await page
    .getByRole("dialog", { name: "Navigation" })
    .getByRole("button", { name: "Queue" })
    .click();

  const sheet = page.getByRole("dialog", { name: "Queue" });
  await expect(sheet).toBeVisible();
  await page.waitForTimeout(500);
  expect(
    await sheet.evaluate((el) => el.contains(document.activeElement)),
  ).toBe(true);
});

const PAGE_TITLES = [
  ["/", /^Today, /],
  ["/explore", "Explore"],
  ["/library", "Library"],
  ["/you", "You"],
  ["/taste", "Your taste"],
  ["/playlists", "Playlists"],
  ["/insights", "Insights"],
  ["/models", "Ranking models"],
  ["/settings", "Settings"],
  ["/status", "Extractor status"],
  ["/search", "Search YouTube"],
  ["/tags/woodworking", "woodworking"],
] as const;

for (const [path, title] of PAGE_TITLES) {
  test(`${path} has one h1, its title`, async ({ page }) => {
    await page.goto(path);

    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toHaveCount(1);
    await expect(heading).toHaveText(title);
  });
}

test("focus scrolls clear of the sticky bars", async ({ page }) => {
  const scrollPadding = () =>
    page.evaluate(
      () => getComputedStyle(document.documentElement).scrollPaddingTop,
    );

  await open(page, "/history");
  expect(await scrollPadding()).toBe("56px");
  // The feed has a bar of chips under the masthead.
  await open(page, "/");
  expect(await scrollPadding()).toBe("112px");
});

test("the queue is a sheet opened from the masthead", async ({ page }) => {
  const [first, second] = [WOODWORKING.videos[0], BIRDWATCHING.videos[0]];
  await open(page, "/");
  const queueButton = page
    .getByRole("banner")
    .getByRole("button", { name: /^Queue/ });
  await expect(queueButton).toHaveAccessibleName("Queue");

  // Queue two videos from the feed, with the cards' "Later" buttons.
  for (const video of [first, second]) {
    await cardButton(feedItem(page, video.title), "Later").click();
  }
  await expect(queueButton).toHaveAccessibleName("Queue, 2 videos");

  await queueButton.click();
  const sheet = page.getByRole("dialog", { name: "Queue" });
  await expect(sheet).toBeVisible();
  // Focus starts on Close, not on the Clear button before it.
  await expect(
    sheet.getByRole("button", { name: "Close queue" }),
  ).toBeFocused();
  await expect(sheet).toContainText("2 videos");
  const rows = sheet.getByRole("list", { name: "Queue" }).getByRole("listitem");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText(first.title);

  // Reorder.
  await rows
    .nth(1)
    .getByRole("button", { name: `More actions for ${second.title}` })
    .click();
  await page.getByRole("menuitem", { name: "Move to top" }).click();
  await expect(rows.first()).toContainText(second.title);
  await expect(sheet.getByRole("status").first()).toContainText(
    `Moved “${second.title}” to position 1.`,
  );

  // Add by pasted link. (Enter, not the button: the dev server's devtools
  // button floats over the sheet's bottom corner.)
  const added = WOODWORKING.videos[1];
  const paste = sheet.getByLabel("Add a video by link or id");
  await paste.fill(`https://youtu.be/${added.id}`);
  await paste.press("Enter");
  await expect(rows).toHaveCount(3);
  await expect(rows.last()).toContainText(added.title);

  // Remove one.
  await rows
    .last()
    .getByRole("button", { name: /^More actions for / })
    .click();
  await page.getByRole("menuitem", { name: "Remove from queue" }).click();
  await expect(rows).toHaveCount(2);

  // Clearing asks first.
  await sheet.getByRole("button", { name: "Clear", exact: true }).click();
  await sheet.getByRole("button", { name: "Keep" }).click();
  await expect(rows).toHaveCount(2);
  await sheet.getByRole("button", { name: "Clear", exact: true }).click();
  await sheet.getByRole("button", { name: "Clear all" }).click();
  await expect(sheet.getByText("Your queue is empty.")).toBeVisible();

  // Escape closes it and hands focus back to the button, now without a count.
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  await expect(queueButton).toBeFocused();
  await expect(queueButton).toHaveAccessibleName("Queue");
});

test("on a watch page the sheet marks the video playing", async ({
  page,
  request,
}) => {
  const [first, second] = WOODWORKING.videos;
  for (const video of [first, second]) {
    const response = await request.post(`${API_URL}/queue`, {
      data: { video_id: video.id },
    });
    expect(response.ok()).toBe(true);
  }

  await open(page, `/watch/${second.id}`);
  await page
    .getByRole("banner")
    .getByRole("button", { name: /^Queue/ })
    .click();

  const sheet = page.getByRole("dialog", { name: "Queue" });
  await expect(sheet).toContainText("2 videos · playing 2 of 2");
  const rows = sheet.getByRole("list", { name: "Queue" }).getByRole("listitem");
  await expect(rows.nth(1)).toHaveAttribute("aria-current", "true");
  await expect(rows.nth(0)).not.toHaveAttribute("aria-current", "true");

  // A row's title leads to its watch page and closes the sheet.
  await rows.nth(0).getByRole("link", { name: first.title }).click();
  await expect(page).toHaveURL(`/watch/${first.id}`);
  await expect(sheet).toHaveCount(0);
  await expect(page.getByRole("main")).toBeFocused();
});

test("the Library's Queue card opens the queue sheet", async ({ page }) => {
  await open(page, "/library");

  const card = page
    .getByRole("main")
    .getByRole("button", { name: "Queue", exact: true });
  await card.click();

  const sheet = page.getByRole("dialog", { name: "Queue" });
  await expect(sheet).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  await expect(card).toBeFocused();
});

test("the account menu has Settings, Status and Log out", async ({ page }) => {
  await open(page, "/");
  const account = page.getByRole("button", { name: "Account menu" });

  await account.click();
  await expect(page.getByRole("menuitem")).toHaveText([
    "Settings",
    "Status",
    "Log out",
  ]);
  await page.getByRole("menuitem", { name: "Settings" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Settings" }),
  ).toBeVisible();

  await account.click();
  await page.getByRole("menuitem", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login/);
});

test("an unknown address shows the app's frame and a way back", async ({
  page,
}) => {
  await page.goto("/no-such-page");

  await expect(
    page.getByRole("heading", { level: 1, name: "Page not found" }),
  ).toBeVisible();
  await expect(page.getByText("This page doesn't exist.")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await page.getByRole("link", { name: "Go to Today" }).click();
  await expect(page).toHaveURL("/");
});

test("a page that can't load keeps the frame, and can be tried again", async ({
  page,
}) => {
  await open(page, "/you");
  // Stand in for the API being down: the server functions fail.
  await page.route("**/_serverFn/**", (route) => route.abort());

  await page
    .getByRole("main")
    .getByRole("link", { name: "Models", exact: true })
    .click();

  const alert = page.getByRole("alert");
  await expect(alert).toContainText("Couldn't load this page.");
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await expect(alert.getByRole("link", { name: "Go to Today" })).toBeVisible();

  await page.unroute("**/_serverFn/**");
  await alert.getByRole("button", { name: "Try again" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Ranking models" }),
  ).toBeVisible();
});
