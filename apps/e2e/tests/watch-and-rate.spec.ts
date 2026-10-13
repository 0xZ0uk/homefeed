import {
  WOODWORKING,
  apiGet,
  expect,
  open,
  waitForHydration,
  feedItem,
  test,
} from "./fixtures";

const video = WOODWORKING.videos[1];

test("watch a video and rate it", async ({ page, request }) => {
  await open(page, "/");
  await feedItem(page, video.title)
    .getByRole("link", { name: video.title })
    .click();

  await expect(page).toHaveURL(`/watch/${video.id}`);
  await expect(page.getByRole("heading", { name: video.title })).toBeVisible();
  await expect(page.getByText("Not rated yet.")).toBeVisible();

  // One tap saves the tier; a second refines it and closes the picker.
  await page.getByRole("button", { name: "Rate", exact: true }).click();
  const tiers = page.getByRole("group", { name: "Tier" });
  await tiers.getByRole("button", { name: "A", exact: true }).click();
  await expect(page.getByText("Saved A.")).toBeVisible();
  await page
    .getByRole("group", { name: /^Refine A/ })
    .getByRole("button", { name: "A+", exact: true })
    .click();

  await expect(tiers).toBeHidden();
  await expect(page.getByText("Your rating: A+")).toBeVisible();
  const saved = await apiGet<{ grade: string }>(
    request,
    `/ratings/${video.id}`,
  );
  expect(saved.body.grade).toBe("A+");

  // The rating sticks across visits and can be changed.
  await page.reload();
  await waitForHydration(page);
  await expect(page.getByText("Your rating: A+")).toBeVisible();
  await page.getByRole("button", { name: "Change", exact: true }).click();
  await page
    .getByRole("group", { name: "Tier" })
    .getByRole("button", { name: "C", exact: true })
    .click();
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await expect(page.getByText("Your rating: C")).toBeVisible();
  const changed = await apiGet<{ grade: string }>(
    request,
    `/ratings/${video.id}`,
  );
  expect(changed.body.grade).toBe("C");
});
