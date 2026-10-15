import type { Page } from "@playwright/test";

import {
  DISCOVERY,
  OUTSIDE,
  actionStatus,
  cardButton,
  isServerFn,
  seedOutside,
} from "./cards";
import { API_URL } from "./env";
import { expect, open, test } from "./fixtures";

const WILDCARD = "Wildcard: outside the topics you follow";

/** The end of the feed: its heading, text and the button for wildcards. */
function end(page: Page) {
  return page.getByRole("region", { name: "That's today." });
}

/** Press "Show more" until the feed has nothing more to give. */
async function showEverything(page: Page) {
  const more = page.getByRole("button", { name: "Show more" });
  const ending = page.getByRole("heading", { name: "That's today." });
  for (let presses = 0; presses < 6 && !(await ending.isVisible()); presses++) {
    // Wait for the answer, not just the button: it still says "Show more" for a
    // moment after it was pressed.
    const loaded = page.waitForResponse((response) =>
      isServerFn(new URL(response.url()), "loadMoreFeed"),
    );
    await more.click();
    await loaded;
    // Back to the button, or on to the end.
    await expect(more.or(ending)).toBeVisible();
  }
  await expect(ending).toBeVisible();
}

test("the feed ends with a closing block once Show more has nothing more", async ({
  page,
}) => {
  await open(page, "/");
  const closing = page.getByRole("heading", { name: "That's today." });
  await expect(closing).toHaveCount(0);

  // The page ends in the button while it can add more.
  const more = page.getByRole("button", { name: "Show more" });
  await more.click();
  await expect(
    page.getByRole("status").filter({ hasText: "Added 1 more video." }),
  ).toBeVisible();
  await expect(more).toBeVisible();
  await expect(closing).toHaveCount(0);

  await more.click();

  await expect(closing).toBeVisible();
  await expect(page.getByRole("button", { name: "Show more" })).toHaveCount(0);
  await expect(end(page)).toContainText(
    "You've seen everything the feed found.",
  );
  await expect(end(page)).toContainText(/Next feed (tomorrow )?at 6:00\./);
  await expect(
    end(page).getByRole("button", { name: "Show 3 wildcards" }),
  ).toBeVisible();
  // It comes after the last card, and the live region that says so is there.
  const [last, block] = await Promise.all([
    page.getByRole("region", { name: /^From your channels/ }).boundingBox(),
    end(page).boundingBox(),
  ]);
  expect(block!.y).toBeGreaterThanOrEqual(last!.y + last!.height - 1);
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "That's everything for today." }),
  ).toBeAttached();
});

test("Show 3 wildcards adds three videos from outside the topics I follow", async ({
  page,
  request,
}) => {
  const added = await request.post(`${API_URL}/__e2e__/pool`);
  expect(added.ok()).toBe(true);
  await open(page, "/");
  await showEverything(page);

  // Not fetched until asked for: the status is a live region, empty at first.
  const status = end(page).getByRole("status");
  await expect(status).toHaveText("");
  await expect(end(page).getByRole("list", { name: "Wildcards" })).toHaveCount(
    0,
  );
  await end(page).getByRole("button", { name: "Show 3 wildcards" }).click();

  const cards = end(page)
    .getByRole("list", { name: "Wildcards" })
    .getByRole("listitem");
  await expect(cards).toHaveCount(3);
  await expect(status).toHaveText("Added 3 wildcards below.");
  for (const card of await cards.all()) {
    // Each says why it's here, and is new to me.
    await expect(card).toContainText(WILDCARD);
    await expect(card).toContainText("New to you");
    await expect(card.getByRole("link").first()).toHaveText(/^Pool video \d$/);
    await expect(cardButton(card, "Details")).toBeVisible();
  }
  // They're asked for once: the button is gone.
  await expect(
    end(page).getByRole("button", { name: "Show 3 wildcards" }),
  ).toHaveCount(0);

  // Details says the same, with the score behind it.
  await cardButton(cards.first(), "Details").click();
  const details = page.getByRole("dialog", { name: "Why this is here" });
  await expect(details).toContainText(WILDCARD);
  await page.keyboard.press("Escape");
});

test("the wildcards are the same all day, and are not what the page shows already", async ({
  page,
  request,
}) => {
  await seedOutside(request);
  await request.post(`${API_URL}/__e2e__/pool`);
  await open(page, "/");
  await showEverything(page);

  async function wildcards() {
    await end(page).getByRole("button", { name: "Show 3 wildcards" }).click();
    const links = end(page)
      .getByRole("list", { name: "Wildcards" })
      .getByRole("listitem")
      .getByRole("heading", { level: 3 });
    await expect(links).toHaveCount(3);
    return (await links.allTextContents()).sort();
  }
  const first = await wildcards();

  // None of the videos the feed (or Discovery) has: these are from further back.
  for (const title of first) expect(title).toMatch(/^Pool video \d$/);
  for (const shown of [OUTSIDE.title, DISCOVERY.title]) {
    expect(first).not.toContain(shown);
  }
  // Another visit, the same three.
  await open(page, "/");
  await showEverything(page);
  expect(await wildcards()).toEqual(first);
});

test("a wildcard has the quick actions of any card", async ({
  page,
  request,
}) => {
  await request.post(`${API_URL}/__e2e__/pool`);
  await open(page, "/");
  await showEverything(page);
  await end(page).getByRole("button", { name: "Show 3 wildcards" }).click();
  const card = end(page)
    .getByRole("list", { name: "Wildcards" })
    .getByRole("listitem")
    .first();
  const title = (await card.getByRole("heading", { level: 3 }).textContent())!;

  await cardButton(card, "More like this").click();
  await expect(cardButton(card, "More like this")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(
    actionStatus(page, `Marked “${title}” as more like this.`),
  ).toBeVisible();

  await cardButton(card, "Later").click();
  await expect(
    actionStatus(page, `Added “${title}” to your queue.`),
  ).toBeVisible();
  await expect(cardButton(card, "Later")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("with nothing outside the topics I follow, it says so", async ({
  page,
}) => {
  await open(page, "/");
  await showEverything(page);

  await end(page).getByRole("button", { name: "Show 3 wildcards" }).click();

  await expect(end(page).getByRole("status")).toContainText(
    "No wildcards today: nothing outside the topics you follow is waiting.",
  );
  await expect(end(page).getByRole("list", { name: "Wildcards" })).toHaveCount(
    0,
  );
});
