import { WOODWORKING, expect, open, test } from "./fixtures";

const [, workbench] = WOODWORKING.videos;
// Seeded with the same tag but not in today's feed.
const dovetails = { id: "wood0000003", title: "Cutting dovetails by hand" };

test("a tag chip on the watch page leads to the tag page", async ({ page }) => {
  await open(page, `/watch/${workbench.id}`);
  await page
    .getByRole("list", { name: "Tags" })
    .getByRole("link", { name: "woodworking" })
    .click();

  await expect(page).toHaveURL("/tags/woodworking");
  await expect(
    page.getByRole("heading", { name: "woodworking" }),
  ).toBeVisible();
  await expect(page.getByText("2 videos")).toBeVisible();
  // Every video carrying the tag, newest published first (the seed uploads
  // the later ones longer ago).
  const cards = page
    .getByRole("list", { name: "Videos" })
    .getByRole("listitem");
  await expect(cards).toHaveCount(2);
  await expect(cards.getByRole("link")).toHaveText([
    workbench.title,
    dovetails.title,
  ]);

  // A card leads back to its watch page.
  await cards.getByRole("link", { name: dovetails.title }).click();
  await expect(page).toHaveURL(`/watch/${dovetails.id}`);
});

test("an unknown tag shows a not-found state", async ({ page }) => {
  await open(page, "/tags/no-such-tag");

  await expect(page.getByText("There's no such tag.")).toBeVisible();
});
