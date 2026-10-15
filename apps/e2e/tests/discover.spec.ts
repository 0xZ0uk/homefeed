import type { Page } from "@playwright/test";

import { API_URL } from "./env";
import {
  METALWORKING,
  apiGet,
  expect,
  likeWoodworking,
  open,
  test,
} from "./fixtures";

interface Channel {
  channel_id: string;
  trial_until: string | null;
}
interface Hide {
  channel_id: string;
  kind: string;
}

/** The suggestion card of the channel titled `title`. */
function card(page: Page, title: string) {
  return page
    .getByRole("list", { name: "Suggested channels" })
    .getByRole("listitem")
    .filter({ has: page.getByRole("heading", { name: title }) });
}

/** A line of the page's live regions that says `text`. */
function said(page: Page, text: string | RegExp) {
  return page.getByRole("status").filter({ hasText: text });
}

test.beforeEach(async ({ request }) => {
  await likeWoodworking(request);
});

test("size up a suggested channel, then try it for two weeks", async ({
  page,
  request,
}) => {
  await open(page, "/discover");
  await expect(
    page.getByRole("heading", { level: 1, name: "Discover" }),
  ).toBeVisible();
  const metal = card(page, METALWORKING.title);
  await expect(metal).toContainText(
    "Featured by Woodworking, a channel you love",
  );
  await expect(metal).toContainText("@metal · 48K subscribers");
  // What its stored videos are about, by how strongly they carry each tag.
  await expect(
    metal
      .getByRole("list", { name: "Topics of Metalworking" })
      .getByRole("listitem"),
  ).toHaveText(["metalworking", "welding", "forging"]);

  // Every card offers the same four decisions, none of them a filled button.
  for (const name of [
    `Subscribe to ${METALWORKING.title}`,
    "Try for 2 weeks",
    "Not now",
    "Hide channel",
  ]) {
    await expect(metal.getByRole("button", { name })).toBeVisible();
  }

  // The preview loads the latest uploads only once it is opened.
  const preview = metal.getByRole("button", {
    name: `Preview ${METALWORKING.title}`,
  });
  await expect(preview).toHaveAttribute("aria-expanded", "false");
  await preview.click();
  await expect(preview).toHaveAttribute("aria-expanded", "true");
  const uploads = metal.getByRole("list", {
    name: `Latest uploads of ${METALWORKING.title}`,
  });
  await expect(uploads.getByRole("link")).toHaveCount(3);
  for (const video of METALWORKING.videos) {
    const link = uploads.getByRole("link", { name: video.title });
    await expect(link).toHaveAttribute("href", `/watch/${video.id}`);
  }
  await expect(uploads).toContainText("10:00");
  await preview.click();
  await expect(preview).toHaveAttribute("aria-expanded", "false");

  await metal.getByRole("button", { name: "Try for 2 weeks" }).click();
  await expect(
    said(page, "Started a 2-week trial of Metalworking"),
  ).toBeVisible();
  await expect(metal).toHaveCount(0);
  const { body } = await apiGet<Channel[]>(request, "/channels");
  const trial = body.find((c) => c.channel_id === METALWORKING.id);
  const days = (Date.parse(trial?.trial_until ?? "") - Date.now()) / 86_400_000;
  expect(days).toBeGreaterThan(13.9);
  expect(days).toBeLessThan(14.1);

  // On Subscriptions the trial counts down, and can be kept.
  await open(page, "/subscriptions");
  const row = page
    .getByRole("list", { name: "Subscriptions", exact: true })
    .getByRole("listitem")
    .filter({ hasText: METALWORKING.title });
  await expect(row).toContainText("Trial · 14 days left");
  await row.getByRole("button", { name: `Keep ${METALWORKING.title}` }).click();
  await expect(said(page, "Kept Metalworking.")).toBeVisible();
  await expect(row).not.toContainText("Trial ·");
  await expect(row.getByRole("button", { name: /^Keep/ })).toHaveCount(0);
  await expect
    .poll(async () => {
      const { body } = await apiGet<Channel[]>(request, "/channels");
      return body.find((c) => c.channel_id === METALWORKING.id)?.trial_until;
    })
    .toBeNull();
});

test("undo subscribing from a suggestion", async ({ page, request }) => {
  await open(page, "/discover");
  const metal = card(page, METALWORKING.title);

  await metal
    .getByRole("button", { name: `Subscribe to ${METALWORKING.title}` })
    .click();
  await expect(said(page, "Subscribed to Metalworking.")).toBeVisible();
  await expect(metal).toHaveCount(0);

  await said(page, "Subscribed to Metalworking.")
    .getByRole("button", { name: "Undo" })
    .click();
  await expect(said(page, "Unsubscribed from Metalworking.")).toBeVisible();
  await expect(metal).toBeVisible();
  const { body } = await apiGet<Channel[]>(request, "/channels");
  expect(body.map((c) => c.channel_id)).not.toContain(METALWORKING.id);
});

test("Not now skips a channel here; Hide channel also keeps its videos out of the feed", async ({
  page,
  request,
}) => {
  await open(page, "/discover");
  const metal = card(page, METALWORKING.title);

  await metal.getByRole("button", { name: "Not now" }).click();
  await expect(said(page, "Skipped Metalworking in Discover.")).toBeVisible();
  await expect(metal).toHaveCount(0);
  const skipped = await apiGet<Hide[]>(request, "/channel-hides");
  expect(skipped.body).toMatchObject([
    { channel_id: METALWORKING.id, kind: "dismissed" },
  ]);

  await said(page, "Skipped Metalworking in Discover.")
    .getByRole("button", { name: "Undo" })
    .click();
  await expect(said(page, "Restored Metalworking.")).toBeVisible();
  await expect(metal).toBeVisible();

  await metal.getByRole("button", { name: "Hide channel" }).click();
  await expect(
    said(page, "Hid Metalworking from your feed and Discover."),
  ).toBeVisible();
  const hidden = await apiGet<Hide[]>(request, "/channel-hides");
  expect(hidden.body).toMatchObject([
    { channel_id: METALWORKING.id, kind: "blocked" },
  ]);

  // Settings words the same two kinds the same way.
  await open(page, "/settings");
  const list = page
    .getByRole("region", { name: "Hidden channels" })
    .getByRole("list", { name: "Hidden channels" });
  const item = list.getByRole("listitem").filter({
    hasText: METALWORKING.title,
  });
  await expect(item).toContainText("Hidden from feed and Discover");
  await item.getByRole("button", { name: /^Only skip in Discover/ }).click();
  await expect(item).toContainText("Skipped in Discover");
  await expect(
    item.getByRole("button", { name: /^Only skip in Discover/ }),
  ).toHaveCount(0);

  // Restoring puts it back among the suggestions.
  await item.getByRole("button", { name: /^Restore/ }).click();
  await expect(item).toHaveCount(0);
  await open(page, "/discover");
  await expect(card(page, METALWORKING.title)).toBeVisible();
});

test("end a trial from Subscriptions: unsubscribed and not suggested again", async ({
  page,
  request,
}) => {
  // The channel is known to Homefeed once its page has been fetched.
  await request.get(`${API_URL}/channels/${METALWORKING.id}`);
  const started = await request.post(
    `${API_URL}/channels/${METALWORKING.id}/trial`,
  );
  expect(started.status()).toBe(201);

  await open(page, "/subscriptions");
  const row = page
    .getByRole("list", { name: "Subscriptions", exact: true })
    .getByRole("listitem")
    .filter({ hasText: METALWORKING.title });
  await row
    .getByRole("button", { name: `End trial of ${METALWORKING.title}` })
    .click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("End the trial of Metalworking?");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(row).toBeVisible();

  await row
    .getByRole("button", { name: `End trial of ${METALWORKING.title}` })
    .click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "End trial" })
    .click();
  await expect(said(page, "Ended the trial of Metalworking.")).toBeVisible();
  await expect(row).toHaveCount(0);

  const hides = await apiGet<Hide[]>(request, "/channel-hides");
  expect(hides.body).toMatchObject([
    { channel_id: METALWORKING.id, kind: "dismissed" },
  ]);
  await open(page, "/discover");
  await expect(card(page, METALWORKING.title)).toHaveCount(0);
});
