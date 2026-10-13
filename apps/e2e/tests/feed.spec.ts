import {
  BIRDWATCHING,
  WOODWORKING,
  expect,
  open,
  feedItem,
  feedList,
  test,
} from "./fixtures";

test("view today's feed", async ({ page }) => {
  await open(page, "/");

  await expect(page.getByRole("heading", { name: /^Today/ })).toBeVisible();
  const items = feedList(page).getByRole("listitem");
  const titles = [...WOODWORKING.videos, ...BIRDWATCHING.videos].map(
    (v) => v.title,
  );
  for (const title of titles) {
    await expect(feedItem(page, title)).toBeVisible();
  }
  // The neutral-prior feed puts the newest uploads (Woodworking's) first.
  await expect(items.first()).toContainText(WOODWORKING.videos[0].title);
  await expect(feedItem(page, WOODWORKING.videos[0].title)).toContainText(
    WOODWORKING.title,
  );

  // Each item explains itself and links to its watch page.
  const first = feedItem(page, WOODWORKING.videos[0].title);
  await first.getByRole("link", { name: WOODWORKING.videos[0].title }).click();
  await expect(page).toHaveURL(`/watch/${WOODWORKING.videos[0].id}`);
  await expect(
    page.getByRole("heading", { name: WOODWORKING.videos[0].title }),
  ).toBeVisible();
});
