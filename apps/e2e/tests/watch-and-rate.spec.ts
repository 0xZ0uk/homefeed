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
  // Its LLM tags, most confident first.
  await expect(
    page.getByRole("list", { name: "Tags" }).getByRole("listitem"),
  ).toHaveText(["workbench", "woodworking", "hand tools"]);
  await expect(page.getByText("Not rated yet.")).toBeVisible();

  // The slider starts mid-scale; nothing is saved until "Save".
  await page.getByRole("button", { name: "Rate", exact: true }).click();
  const slider = page.getByRole("slider", { name: "Score" });
  await expect(slider).toBeFocused();
  await expect(slider).toHaveAttribute("aria-valuetext", "5.5 out of 10");
  await slider.press("End");
  for (let i = 0; i < 13; i++) await slider.press("ArrowLeft");
  await page.getByRole("button", { name: "Save 8.7", exact: true }).click();

  await expect(slider).toBeHidden();
  await expect(page.getByText("Your rating: 8.7")).toBeVisible();
  const saved = await apiGet<{ score: number }>(
    request,
    `/ratings/${video.id}`,
  );
  expect(saved.body.score).toBe(8.7);

  // The rating sticks across visits and can be changed.
  await page.reload();
  await waitForHydration(page);
  await expect(page.getByText("Your rating: 8.7")).toBeVisible();
  await page.getByRole("button", { name: "Change", exact: true }).click();
  // It starts at the current score; Page Down moves a whole point.
  const change = page.getByRole("slider", { name: "Score" });
  await expect(change).toHaveAttribute("aria-valuetext", "8.7 out of 10");
  for (let i = 0; i < 4; i++) await change.press("PageDown");
  for (let i = 0; i < 7; i++) await change.press("ArrowLeft");
  await page.getByRole("button", { name: "Save 4.0", exact: true }).click();
  await expect(page.getByText("Your rating: 4.0")).toBeVisible();
  const changed = await apiGet<{ score: number }>(
    request,
    `/ratings/${video.id}`,
  );
  expect(changed.body.score).toBe(4);
});
