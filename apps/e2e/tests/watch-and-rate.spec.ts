import { API_URL } from "./env";
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
// An inline image, so nothing is fetched.
const PICTURE = `data:image/svg+xml,${encodeURIComponent(
  "<svg xmlns='http://www.w3.org/2000/svg' width='72' height='72'><rect width='72' height='72' fill='#8a5a2b'/></svg>",
)}`;

test("watch a video and rate it", async ({ page, request }) => {
  // The channel has a picture, as once it has been looked up.
  const picture = await request.post(`${API_URL}/__e2e__/channel-picture`, {
    data: { channel_id: WOODWORKING.id, url: PICTURE },
  });
  expect(picture.ok(), "giving the channel a picture").toBe(true);

  await open(page, "/");
  await feedItem(page, video.title)
    .getByRole("link", { name: video.title })
    .click();

  await expect(page).toHaveURL(`/watch/${video.id}`);
  // The video's title is the page's heading.
  await expect(
    page.getByRole("heading", { name: video.title, level: 1 }),
  ).toBeVisible();
  // The channel shows its picture, not just an initial.
  await expect(page.locator('img[src^="data:image/svg+xml"]')).toBeVisible();
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
  // It is labelled on the page, says what its ends mean, and numbers its faces.
  await expect(
    page.getByText("Rate this video", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("1 = awful · 10 = amazing")).toBeVisible();
  for (const score of [1, 5, 10]) {
    await expect(scale.getByText(String(score), { exact: true })).toBeVisible();
  }

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

  // Pressing on one face and dragging to another picks the one let go on.
  const from = await face("Bad, 3 out of 10").boundingBox();
  const to = await face("Excellent, 9 out of 10").boundingBox();
  if (!from || !to) throw new Error("The faces aren't laid out");
  const row = from.y + 22; // the face's own row, above its number
  await page.mouse.move(from.x + from.width / 2, row);
  await page.mouse.down();
  await page.mouse.move(to.x + to.width / 2, row, { steps: 10 });
  await page.mouse.up();
  await expect(face("Excellent, 9 out of 10")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect.poll(storedScore).toBe(9);
});
