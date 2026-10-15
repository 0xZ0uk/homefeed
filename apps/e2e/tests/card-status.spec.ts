import { WOODWORKING, expect, feedItem, open, test } from "./fixtures";
import { actionStatus, cardButton } from "./cards";

const video = WOODWORKING.videos[0];
const MARKED = `Marked “${video.title}” as more like this.`;

test("a status goes after a while, with a button to undo it until then", async ({
  page,
}) => {
  await open(page, "/");
  await page.clock.install();
  await cardButton(feedItem(page, video.title), "More like this").click();
  await expect(actionStatus(page, MARKED)).toBeVisible();

  await page.clock.fastForward(5_000);
  await expect(actionStatus(page, MARKED)).toBeVisible();
  await page.clock.fastForward(6_000);

  await expect(actionStatus(page, MARKED)).toHaveCount(0);
  // The card keeps what was pressed.
  await expect(
    cardButton(feedItem(page, video.title), "More like this"),
  ).toHaveAttribute("aria-pressed", "true");
});

test("a status stays while the pointer is on its button, or focus is in it", async ({
  page,
}) => {
  await open(page, "/");
  await page.clock.install();
  await cardButton(feedItem(page, video.title), "More like this").click();
  const status = actionStatus(page, MARKED);
  await expect(status).toBeVisible();

  // The pointer on its button holds it...
  await status.getByRole("button", { name: "Undo" }).hover();
  await page.clock.fastForward(30_000);
  await expect(status).toBeVisible();
  // ...and it goes a while after the pointer has left.
  await page.mouse.move(2, 2);
  await page.clock.fastForward(11_000);
  await expect(status).toHaveCount(0);

  // Keyboard focus in it holds it as well: Tab from the sort button to Undo.
  await cardButton(feedItem(page, video.title), "Less like this").click();
  const next = actionStatus(page, "Marked");
  await expect(next).toBeVisible();
  await page.getByRole("button", { name: /^Sort:/ }).focus();
  await page.keyboard.press("Tab");
  await expect(next.getByRole("button", { name: "Undo" })).toBeFocused();
  await page.clock.fastForward(30_000);
  await expect(next).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(actionStatus(page, "Undone.")).toBeVisible();
});

test("an Undo with the keyboard leaves focus on the status", async ({
  page,
}) => {
  await open(page, "/");
  await cardButton(feedItem(page, video.title), "More like this").click();
  const status = actionStatus(page, MARKED);
  await expect(status).toBeVisible();

  await page.getByRole("button", { name: /^Sort:/ }).focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");

  // The button pressed is gone; focus isn't lost with it.
  const undone = actionStatus(page, "Undone.");
  await expect(undone).toBeVisible();
  await expect(undone).toBeFocused();
});

test("a status the mouse user was given focus on still goes", async ({
  page,
}) => {
  await open(page, "/");
  // Time flows as usual until the test jumps ahead.
  await page.clock.install();
  await page.clock.resume();
  await feedItem(page, video.title)
    .getByRole("button", { name: `More actions for ${video.title}` })
    .click();
  await page.getByRole("menuitem", { name: "Clickbait" }).click();
  const status = actionStatus(page, `Dismissed “${video.title}”.`);

  // Focus is moved to it (the card's menu is gone)...
  await expect(status).toBeFocused();
  // ...yet nobody is using it: it goes like any other.
  await page.clock.fastForward(11_000);
  await expect(status).toHaveCount(0);
});

test("a status the keyboard user was given focus on stays, for the Undo", async ({
  page,
}) => {
  await open(page, "/");
  await page.clock.install();
  await page.clock.resume();
  const menu = feedItem(page, video.title).getByRole("button", {
    name: `More actions for ${video.title}`,
  });
  await menu.focus();
  await page.keyboard.press("Enter");
  await page.getByRole("menuitem", { name: "Clickbait" }).focus();
  await page.keyboard.press("Enter");
  const status = actionStatus(page, `Dismissed “${video.title}”.`);

  await expect(status).toBeFocused();
  // Someone using the keyboard is about to Tab to Undo: it waits for them.
  await page.clock.fastForward(30_000);
  await expect(status).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(status.getByRole("button", { name: "Undo" })).toBeFocused();
});
