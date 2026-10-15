import type { APIRequestContext, Page } from "@playwright/test";

import { API_URL } from "./env";
import {
  BIRDWATCHING,
  GARDENING,
  WOODWORKING,
  apiGet,
  expect,
  open,
  resetWith,
  test,
  waitForHydration,
} from "./fixtures";

interface Channel {
  channel_id: string;
  pinned: boolean;
  muted: boolean;
  muted_until: string | null;
}

function list(page: Page) {
  return page.getByRole("list", { name: "Subscriptions", exact: true });
}

function row(page: Page, title: string) {
  return list(page).getByRole("listitem").filter({ hasText: title });
}

function said(page: Page, text: string | RegExp) {
  return page.getByRole("status").filter({ hasText: text });
}

async function stored(
  request: APIRequestContext,
  channelId: string,
): Promise<Channel | undefined> {
  const { body } = await apiGet<Channel[]>(request, "/channels");
  return body.find((c) => c.channel_id === channelId);
}

test("each channel shows how much of it you watch, and the list sorts by it", async ({
  page,
  request,
}) => {
  // Gardening has six picks; a video of it is rated, the others are not watched.
  await resetWith(request, { noisy: true });
  const rated = await request.put(`${API_URL}/ratings/gard0000001`, {
    data: { score: 8 },
  });
  expect(rated.ok()).toBe(true);

  await open(page, "/subscriptions");
  await expect(
    page.getByRole("heading", { level: 1, name: "Subscriptions" }),
  ).toBeVisible();
  await expect(row(page, GARDENING.title)).toContainText(
    /Watched 1 of 6 picks · avg 8\.0 from 1 rating · last watched (just now|\d+ minutes? ago)/,
  );
  await expect(row(page, WOODWORKING.title)).toContainText(
    "Watched 0 of 3 picks · no ratings yet · never watched",
  );

  const titles = () =>
    list(page).getByRole("listitem").getByRole("link").allTextContents();
  const sortBy = (label: string) =>
    page.getByLabel("Sort by").selectOption({ label });
  await expect
    .poll(titles)
    .toEqual([BIRDWATCHING.title, GARDENING.title, WOODWORKING.title]);
  await sortBy("Most picks");
  await expect
    .poll(titles)
    .toEqual([GARDENING.title, WOODWORKING.title, BIRDWATCHING.title]);
  // The channels with nothing watched come before the one that is, the one
  // with more picks first.
  await sortBy("Least watched");
  await expect
    .poll(titles)
    .toEqual([WOODWORKING.title, BIRDWATCHING.title, GARDENING.title]);
  await sortBy("A–Z");
  await expect
    .poll(titles)
    .toEqual([BIRDWATCHING.title, GARDENING.title, WOODWORKING.title]);
});

test("pin a channel and mute it for a month, then unmute it", async ({
  page,
  request,
}) => {
  await open(page, "/subscriptions");
  const birds = row(page, BIRDWATCHING.title);

  const pinned = birds.getByRole("button", { name: /^Pinned/ });
  await expect(pinned).toHaveAttribute("aria-pressed", "false");
  await pinned.click();
  await expect(pinned).toHaveAttribute("aria-pressed", "true");
  await expect
    .poll(async () => (await stored(request, BIRDWATCHING.id))?.pinned)
    .toBe(true);

  await birds.getByRole("button", { name: /^Mute: / }).click();
  await page.getByRole("menuitem", { name: "Mute for a month" }).click();
  await expect(said(page, /Muted Birdwatching until \w+ \d+\./)).toBeVisible();
  await expect(birds).toContainText("Muted until");
  await expect(birds.getByRole("button", { name: /^Muted: / })).toBeVisible();
  const muted = await stored(request, BIRDWATCHING.id);
  const days = (Date.parse(muted?.muted_until ?? "") - Date.now()) / 86_400_000;
  expect(days).toBeGreaterThan(29.9);
  expect(days).toBeLessThan(30.1);
  expect(muted?.muted).toBe(false);

  await birds.getByRole("button", { name: /^Muted: / }).click();
  await page.getByRole("menuitem", { name: "Unmute" }).click();
  await expect(said(page, "Unmuted Birdwatching.")).toBeVisible();
  await expect(birds).not.toContainText("Muted until");
  await expect
    .poll(async () => (await stored(request, BIRDWATCHING.id))?.muted_until)
    .toBeNull();
});

test("unsubscribing asks first, naming the channel", async ({
  page,
  request,
}) => {
  await open(page, "/subscriptions");
  const birds = row(page, BIRDWATCHING.title);

  await birds
    .getByRole("button", { name: `Unsubscribe from ${BIRDWATCHING.title}` })
    .click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("Unsubscribe from Birdwatching?");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
  expect(await stored(request, BIRDWATCHING.id)).toBeDefined();

  await birds
    .getByRole("button", { name: `Unsubscribe from ${BIRDWATCHING.title}` })
    .click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Unsubscribe" })
    .click();
  await expect(said(page, "Unsubscribed from Birdwatching.")).toBeVisible();
  await expect(birds).toHaveCount(0);
  expect(await stored(request, BIRDWATCHING.id)).toBeUndefined();
});

test.describe("a channel that keeps showing up unwatched", () => {
  test.beforeEach(async ({ request }) => {
    await resetWith(request, { noisy: true });
  });

  const panel = (page: Page) =>
    page.getByRole("region", {
      name: "These channels keep showing up but you don't watch them",
    });

  test("is suggested for muting or unsubscribing; muting can be undone", async ({
    page,
    request,
  }) => {
    await open(page, "/subscriptions");
    const suggestion = panel(page).getByRole("listitem");
    await expect(suggestion).toHaveCount(1);
    await expect(suggestion).toContainText(GARDENING.title);
    await expect(suggestion).toContainText("6 picks, none watched");
    await expect(
      suggestion.getByRole("button", { name: /^Unsubscribe from/ }),
    ).toBeVisible();

    await suggestion.getByRole("button", { name: /^Mute for a month/ }).click();
    await expect(said(page, /Muted Gardening until/)).toBeVisible();
    await expect(panel(page)).toHaveCount(0);
    expect((await stored(request, GARDENING.id))?.muted_until).toBeTruthy();

    await said(page, /Muted Gardening until/)
      .getByRole("button", { name: "Undo" })
      .click();
    await expect(said(page, "Unmuted Gardening.")).toBeVisible();
    await expect(panel(page)).toBeVisible();
    expect((await stored(request, GARDENING.id))?.muted_until).toBeNull();
  });

  test("can be dismissed, and stays dismissed", async ({ page }) => {
    await open(page, "/subscriptions");
    await expect(panel(page)).toBeVisible();

    await panel(page).getByRole("button", { name: "Not now" }).click();
    await expect(panel(page)).toHaveCount(0);

    await page.reload();
    await waitForHydration(page);
    await expect(row(page, GARDENING.title)).toBeVisible();
    await expect(panel(page)).toHaveCount(0);
  });
});
