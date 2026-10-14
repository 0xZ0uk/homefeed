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
  // The scale is on the page with no face lit.
  const scale = page.getByRole("group", { name: "Rate this video" });
  const face = (name: string) => scale.getByRole("button", { name });
  const storedScore = async () => {
    const { status, body } = await apiGet<{ score: number }>(
      request,
      `/ratings/${video.id}`,
    );
    return status === 404 ? null : body.score;
  };
  await expect(scale.getByRole("button", { pressed: true })).toHaveCount(0);

  // Arrow keys only move focus; Enter saves at once.
  await face("Great, 8 out of 10").focus();
  await page.keyboard.press("ArrowRight");
  await expect(face("Excellent, 9 out of 10")).toBeFocused();
  await expect(scale.getByRole("button", { pressed: true })).toHaveCount(0);
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("Enter");
  await expect(face("Great, 8 out of 10")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect.poll(storedScore).toBe(8);

  // The rating sticks across visits; clicking another face changes it.
  await page.reload();
  await waitForHydration(page);
  await expect(face("Great, 8 out of 10")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await face("Poor, 4 out of 10").click();
  await expect(face("Poor, 4 out of 10")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect.poll(storedScore).toBe(4);

  // Clicking the lit face again removes the rating; clicking it once more
  // puts it back.
  await face("Poor, 4 out of 10").click();
  await expect(scale.getByRole("button", { pressed: true })).toHaveCount(0);
  await expect.poll(storedScore).toBeNull();
  await face("Poor, 4 out of 10").click();
  await expect.poll(storedScore).toBe(4);

  // Quick clicks save in order: the last one sticks.
  await face("Bad, 3 out of 10").click();
  await face("Amazing, 10 out of 10").click();
  await face("Good, 7 out of 10").click();
  await expect.poll(storedScore).toBe(7);
  await page.reload();
  await waitForHydration(page);
  await expect(face("Good, 7 out of 10")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});
