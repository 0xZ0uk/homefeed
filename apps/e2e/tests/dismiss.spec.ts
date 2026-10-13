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

const video = WOODWORKING.videos[0];

interface Feed {
  items: {
    video_id: string;
    dismissed_at: string | null;
    dismiss_reason: string | null;
  }[];
}

test("dismiss a feed item with a reason", async ({ page, request }) => {
  await open(page, "/");
  const item = feedItem(page, video.title);
  await expect(item).toBeVisible();
  const before = await feedList(page).getByRole("listitem").count();

  await item
    .getByRole("button", { name: `More actions for ${video.title}` })
    .click();
  await page.getByRole("menuitem", { name: "Not interested" }).click();

  await expect(
    page.getByRole("status").filter({ hasText: "Dismissed" }),
  ).toContainText(video.title);
  await expect(item).toHaveCount(0);
  await expect(feedList(page).getByRole("listitem")).toHaveCount(before - 1);

  // Saved: gone after a reload too, with its reason recorded.
  await page.reload();
  await waitForHydration(page);
  await expect(feedList(page)).toBeVisible();
  await expect(feedItem(page, video.title)).toHaveCount(0);
  const { body } = await apiGet<Feed>(request, "/feed/today");
  const saved = body.items.find((i) => i.video_id === video.id);
  expect(saved?.dismissed_at).toBeTruthy();
  expect(saved?.dismiss_reason).toBe("Not interested");
});
