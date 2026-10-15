import {
  WOODWORKING,
  apiGet,
  expect,
  feedItem,
  open,
  test,
  waitForHydration,
} from "./fixtures";
import { actionStatus, cardButton, isServerFn } from "./cards";

const video = WOODWORKING.videos[0];

interface Feed {
  items: { video_id: string; feedback: number | null }[];
}

/** The feedback the API holds for the video. */
async function saved(request: Parameters<typeof apiGet>[0]) {
  const { body } = await apiGet<Feed>(request, "/feed/today");
  return body.items.find((i) => i.video_id === video.id)?.feedback ?? null;
}

test("more like this and less like this are toggles that steer the feed", async ({
  page,
  request,
}) => {
  await open(page, "/");
  const card = feedItem(page, video.title);
  const more = cardButton(card, "More like this");
  const less = cardButton(card, "Less like this");

  await expect(more).toHaveAttribute("aria-pressed", "false");
  await expect(less).toHaveAttribute("aria-pressed", "false");

  await more.click();
  await expect(more).toHaveAttribute("aria-pressed", "true");
  await expect(less).toHaveAttribute("aria-pressed", "false");
  await expect(
    actionStatus(page, `Marked “${video.title}” as more like this.`),
  ).toBeVisible();
  await expect.poll(() => saved(request)).toBe(1);

  // The other one replaces it.
  await less.click();
  await expect(less).toHaveAttribute("aria-pressed", "true");
  await expect(more).toHaveAttribute("aria-pressed", "false");
  await expect.poll(() => saved(request)).toBe(-1);

  // Pressing the pressed one clears it.
  await less.click();
  await expect(less).toHaveAttribute("aria-pressed", "false");
  await expect(actionStatus(page, "Cleared “less like this”")).toBeVisible();
  await expect.poll(() => saved(request)).toBeNull();

  // Feedback isn't a rating.
  expect((await apiGet(request, `/ratings/${video.id}`)).status).toBe(404);
});

test("Undo takes a press back", async ({ page, request }) => {
  await open(page, "/");
  const card = feedItem(page, video.title);
  const more = cardButton(card, "More like this");

  await more.click();
  await expect.poll(() => saved(request)).toBe(1);
  await actionStatus(page, "Marked")
    .getByRole("button", { name: "Undo" })
    .click();

  await expect(more).toHaveAttribute("aria-pressed", "false");
  await expect(actionStatus(page, "Undone.")).toBeVisible();
  await expect.poll(() => saved(request)).toBeNull();
});

test("Undo also takes a clearing back", async ({ page, request }) => {
  await open(page, "/");
  const less = cardButton(feedItem(page, video.title), "Less like this");
  await less.click();
  await expect.poll(() => saved(request)).toBe(-1);
  await less.click();
  await expect(less).toHaveAttribute("aria-pressed", "false");
  await expect.poll(() => saved(request)).toBeNull();

  await actionStatus(page, "Cleared")
    .getByRole("button", { name: "Undo" })
    .click();

  await expect(less).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => saved(request)).toBe(-1);
});

test("feedback is still there after a reload", async ({ page, request }) => {
  await open(page, "/");
  await cardButton(feedItem(page, video.title), "Less like this").click();
  await expect.poll(() => saved(request)).toBe(-1);

  await page.reload();
  await waitForHydration(page);

  await expect(
    cardButton(feedItem(page, video.title), "Less like this"),
  ).toHaveAttribute("aria-pressed", "true");
});

test("quick presses end up as the last one left them", async ({
  page,
  request,
}) => {
  await open(page, "/");
  const card = feedItem(page, video.title);
  const more = cardButton(card, "More like this");
  const less = cardButton(card, "Less like this");

  await more.click();
  await less.click();
  await more.click();

  await expect(more).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => saved(request)).toBe(1);
});

test("a press that can't be saved is taken back, and says so", async ({
  page,
  request,
}) => {
  await open(page, "/");
  await page.route(
    (url) => isServerFn(url, "saveFeedback"),
    (route) => route.abort(),
  );
  const more = cardButton(feedItem(page, video.title), "More like this");

  await more.click();

  await expect(actionStatus(page, "Couldn't save that")).toContainText(
    video.title,
  );
  await expect(more).toHaveAttribute("aria-pressed", "false");
  expect(await saved(request)).toBeNull();
});

test("the status doesn't get in the way of the buttons of the card it is about", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1280, height: 420 });
  await open(page, "/");
  const card = feedItem(page, video.title);
  const more = cardButton(card, "More like this");
  const less = cardButton(card, "Less like this");
  // Put the card's buttons just under the sticky bar, where the status hangs.
  await more.evaluate((button) => {
    window.scrollTo(
      0,
      button.getBoundingClientRect().top + window.scrollY - 140,
    );
  });

  await more.click();

  const status = actionStatus(page, "Marked");
  await expect(status).toBeVisible();
  const [over, button] = await Promise.all([
    status.boundingBox(),
    less.boundingBox(),
  ]);
  expect(over && button, "both are on screen").toBeTruthy();
  const overlap =
    Math.min(over!.y + over!.height, button!.y + button!.height) -
    Math.max(over!.y, button!.y);
  expect(overlap, "the status covers the next button").toBeGreaterThan(0);
  // Pressing there still reaches the button under the status.
  await less.click({ position: { x: 4, y: 4 } });
  await expect(less).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => saved(request)).toBe(-1);
});
