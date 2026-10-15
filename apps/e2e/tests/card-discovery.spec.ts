import { apiGet, expect, open, test } from "./fixtures";
import { DISCOVERY, actionStatus, cardButton, seedOutside } from "./cards";

/** Discovery's cards, the videos the feed below doesn't have. */
function carousel(page: Parameters<typeof open>[0]) {
  return page
    .getByRole("list", { name: "Discovery videos" })
    .getByRole("listitem");
}

/** The feedback the API holds for the Discovery video. */
async function saved(request: Parameters<typeof apiGet>[0]) {
  const { body } = await apiGet<
    { video_id: string; feedback: number | null }[]
  >(request, "/discover/videos");
  return body.find((v) => v.video_id === DISCOVERY.id)?.feedback ?? null;
}

test("a Discovery card says why it's there, like a feed card does", async ({
  page,
  request,
}) => {
  await seedOutside(request);
  await open(page, "/");

  const slide = carousel(page).filter({
    has: page.getByRole("link", { name: DISCOVERY.title, exact: true }),
  });
  await expect(slide).toContainText("Featured by a channel you like");
  await expect(slide).toContainText("New to you");
  await expect(slide).toContainText("Joinery Journal · 25 min");
  await cardButton(slide, "Details").click();
  await expect(
    page.getByRole("dialog", { name: "Why this is here" }),
  ).toContainText("Score breakdown");
});

test("a Discovery card can be steered from, with an Undo", async ({
  page,
  request,
}) => {
  await seedOutside(request);
  await open(page, "/");
  const slide = carousel(page).filter({
    has: page.getByRole("link", { name: DISCOVERY.title, exact: true }),
  });
  const less = cardButton(slide, "Less like this");

  await less.click();

  await expect(less).toHaveAttribute("aria-pressed", "true");
  await expect(
    actionStatus(page, `Marked “${DISCOVERY.title}” as less like this.`),
  ).toBeVisible();
  await expect.poll(() => saved(request)).toBe(-1);

  await actionStatus(page, "Marked")
    .getByRole("button", { name: "Undo" })
    .click();
  await expect(less).toHaveAttribute("aria-pressed", "false");
  await expect.poll(() => saved(request)).toBeNull();
});

test("Later on a Discovery card queues it", async ({ page, request }) => {
  await seedOutside(request);
  await open(page, "/");
  const slide = carousel(page).filter({
    has: page.getByRole("link", { name: DISCOVERY.title, exact: true }),
  });
  const later = cardButton(slide, "Later");
  await expect(later).not.toHaveAttribute("aria-disabled", "true");

  await later.click();

  await expect(later).toHaveAttribute("aria-pressed", "true");
  await expect(
    actionStatus(page, `Added “${DISCOVERY.title}” to your queue.`),
  ).toBeVisible();
  await expect
    .poll(async () =>
      (await apiGet<{ video_id: string }[]>(request, "/queue")).body.map(
        (item) => item.video_id,
      ),
    )
    .toEqual([DISCOVERY.id]);
});
