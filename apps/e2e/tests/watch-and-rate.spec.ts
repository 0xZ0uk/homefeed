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
  await expect(
    page.getByRole("heading", { name: "Rate this video" }),
  ).toBeVisible();

  // The slider is on the page, mid-scale; nothing is saved until "Save".
  const slider = page.getByRole("slider", { name: "Score" });
  await expect(slider).toHaveAttribute("aria-valuetext", "5.5 out of 10");
  await slider.focus();
  await slider.press("End");
  for (let i = 0; i < 13; i++) await slider.press("ArrowLeft");
  await page.getByRole("button", { name: "Save 8.7", exact: true }).click();

  await expect(
    page.getByRole("heading", { name: "Your rating: 8.7" }),
  ).toBeVisible();
  // Saved: the slider stays at the score, with no Save left to press.
  await expect(slider).toHaveAttribute("aria-valuetext", "8.7 out of 10");
  await expect(page.getByRole("button", { name: /^Save/ })).toBeHidden();
  const saved = await apiGet<{ score: number }>(
    request,
    `/ratings/${video.id}`,
  );
  expect(saved.body.score).toBe(8.7);

  // The rating sticks across visits and can be changed; Reset goes back.
  await page.reload();
  await waitForHydration(page);
  await expect(
    page.getByRole("heading", { name: "Your rating: 8.7" }),
  ).toBeVisible();
  const change = page.getByRole("slider", { name: "Score" });
  await expect(change).toHaveAttribute("aria-valuetext", "8.7 out of 10");
  await change.focus();
  await change.press("PageDown");
  await page.getByRole("button", { name: "Reset", exact: true }).click();
  await expect(change).toHaveAttribute("aria-valuetext", "8.7 out of 10");
  // Page Down moves a whole point.
  await change.focus();
  for (let i = 0; i < 4; i++) await change.press("PageDown");
  for (let i = 0; i < 7; i++) await change.press("ArrowLeft");
  await page.getByRole("button", { name: "Save 4.0", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your rating: 4.0" }),
  ).toBeVisible();
  const changed = await apiGet<{ score: number }>(
    request,
    `/ratings/${video.id}`,
  );
  expect(changed.body.score).toBe(4);

  // Removing it can be undone.
  await page.getByRole("button", { name: "Remove rating" }).click();
  await expect(page.getByText("Rating removed.")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Rate this video" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(
    page.getByRole("heading", { name: "Your rating: 4.0" }),
  ).toBeVisible();
});
