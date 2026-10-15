import type { Route } from "@playwright/test";

import {
  WOODWORKING,
  apiGet,
  expect,
  open,
  waitForHydration,
  feedItem,
  feedList,
  test,
} from "./fixtures";
import { actionStatus, isServerFn } from "./cards";
import { API_URL } from "./env";

const video = WOODWORKING.videos[0];

interface Feed {
  date: string;
  items: {
    id: number;
    video_id: string;
    dismissed_at: string | null;
    dismiss_reason: string | null;
  }[];
}

/** The API's copy of the feed item for `video`. */
async function stored(request: Parameters<typeof apiGet>[0]) {
  const { body } = await apiGet<Feed>(request, "/feed/today");
  const item = body.items.find((i) => i.video_id === video.id);
  expect(item).toBeDefined();
  return { date: body.date, item: item! };
}

test("dismiss a feed item with a reason", async ({ page, request }) => {
  await open(page, "/");
  const item = feedItem(page, video.title);
  await expect(item).toBeVisible();
  const before = await feedList(page).getByRole("listitem").count();

  await item
    .getByRole("button", { name: `More actions for ${video.title}` })
    .click();
  // The ways to dismiss are one labelled group.
  const group = page.getByRole("group", { name: "Not for me" });
  await expect(group.getByRole("menuitem")).toHaveText([
    "Not interested",
    "Already seen it",
    "Not in the mood",
    "Clickbait",
    "Too long",
    "No reason",
  ]);
  await page.getByRole("menuitem", { name: "Not interested" }).click();

  await expect(
    page.getByRole("status").filter({ hasText: "Dismissed" }),
  ).toContainText(video.title);
  await expect(item).toHaveCount(0);
  await expect(feedList(page).getByRole("listitem")).toHaveCount(before - 1);

  // Saved: gone after a reload too, with its reason recorded.
  await page.reload();
  await waitForHydration(page);
  await expect(feedList(page).first()).toBeVisible();
  await expect(feedItem(page, video.title)).toHaveCount(0);
  const { item: saved } = await stored(request);
  expect(saved.dismissed_at).toBeTruthy();
  expect(saved.dismiss_reason).toBe("Not interested");
});

test("Undo brings a dismissed card back", async ({ page, request }) => {
  await open(page, "/");
  const before = await feedList(page).getByRole("listitem").count();
  await feedItem(page, video.title)
    .getByRole("button", { name: `More actions for ${video.title}` })
    .click();
  await page.getByRole("menuitem", { name: "Clickbait" }).click();
  const status = actionStatus(page, `Dismissed “${video.title}”.`);
  await expect(status).toBeVisible();
  await expect(feedItem(page, video.title)).toHaveCount(0);

  // The status takes focus (the card's menu is gone), so Undo is next.
  await expect(status).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(status.getByRole("button", { name: "Undo" })).toBeFocused();
  await page.keyboard.press("Enter");

  await expect(actionStatus(page, `Restored “${video.title}”.`)).toBeVisible();
  await expect(feedItem(page, video.title)).toBeVisible();
  await expect(feedList(page).getByRole("listitem")).toHaveCount(before);
  await expect
    .poll(async () => (await stored(request)).item.dismissed_at)
    .toBeNull();
  expect((await stored(request)).item.dismiss_reason).toBeNull();

  // Restored for good: it's on the page after a reload.
  await page.reload();
  await waitForHydration(page);
  await expect(feedItem(page, video.title)).toBeVisible();
});

test("a dismissal that can't be saved is taken back, and says so", async ({
  page,
  request,
}) => {
  await open(page, "/");
  await page.route(
    (url) => isServerFn(url, "dismissItem"),
    (route) => route.abort(),
  );

  await feedItem(page, video.title)
    .getByRole("button", { name: `More actions for ${video.title}` })
    .click();
  await page.getByRole("menuitem", { name: "No reason" }).click();

  await expect(
    actionStatus(page, `Couldn't dismiss “${video.title}”. Try again later.`),
  ).toBeVisible();
  await expect(feedItem(page, video.title)).toBeVisible();
  expect((await stored(request)).item.dismissed_at).toBeNull();
});

test("a restoration that can't be saved dismisses the card again, says so and can be tried again", async ({
  page,
  request,
}) => {
  await open(page, "/");
  await feedItem(page, video.title)
    .getByRole("button", { name: `More actions for ${video.title}` })
    .click();
  await page.getByRole("menuitem", { name: "Too long" }).click();
  await expect(feedItem(page, video.title)).toHaveCount(0);
  await expect
    .poll(async () => (await stored(request)).item.dismissed_at)
    .toBeTruthy();
  const fails = (url: URL) => isServerFn(url, "undismissItem");
  const abort = (route: Route) => route.abort();
  await page.route(fails, abort);

  await actionStatus(page, "Dismissed")
    .getByRole("button", { name: "Undo" })
    .click();

  const failed = actionStatus(page, `Couldn't restore “${video.title}”.`);
  await expect(failed).toBeVisible();
  await expect(feedItem(page, video.title)).toHaveCount(0);
  const { item } = await stored(request);
  expect(item.dismiss_reason).toBe("Too long");

  // The card is out of sight, so the status offers the Undo again.
  await page.unroute(fails, abort);
  await failed.getByRole("button", { name: "Undo" }).click();
  await expect(actionStatus(page, `Restored “${video.title}”.`)).toBeVisible();
  await expect(feedItem(page, video.title)).toBeVisible();
  await expect
    .poll(async () => (await stored(request)).item.dismissed_at)
    .toBeNull();
});

test("an Undo before the dismissal is saved still brings the card back", async ({
  page,
  request,
}) => {
  await open(page, "/");
  // The dismissal takes a while to reach the API.
  await page.route(
    (url) => isServerFn(url, "dismissItem"),
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1_500));
      await route.continue();
    },
  );
  await feedItem(page, video.title)
    .getByRole("button", { name: `More actions for ${video.title}` })
    .click();
  await page.getByRole("menuitem", { name: "Clickbait" }).click();
  await expect(feedItem(page, video.title)).toHaveCount(0);

  const restored = page.waitForResponse((response) =>
    isServerFn(new URL(response.url()), "undismissItem"),
  );
  await actionStatus(page, "Dismissed")
    .getByRole("button", { name: "Undo" })
    .click();
  await expect(feedItem(page, video.title)).toBeVisible();
  // Once the dismissal and then the restoration are saved, the card is still there.
  await restored;
  await expect(feedItem(page, video.title)).toBeVisible();
  expect((await stored(request)).item.dismissed_at).toBeNull();
});

test("a dismissed card on a past feed says so in words, not by fading", async ({
  page,
  request,
}) => {
  const { date, item } = await stored(request);
  const response = await request.post(
    `${API_URL}/feed-items/${item.id}/dismiss`,
    { data: { reason: "Clickbait" } },
  );
  expect(response.ok()).toBe(true);

  await open(page, `/feed/${date}`);

  const card = feedItem(page, video.title);
  await expect(card).toContainText("Dismissed: Clickbait");
  await expect(card).toHaveCSS("opacity", "1");
  // The past feed is fixed: nothing to dismiss or restore.
  await expect(
    card.getByRole("button", { name: `More actions for ${video.title}` }),
  ).toHaveCount(0);
});
