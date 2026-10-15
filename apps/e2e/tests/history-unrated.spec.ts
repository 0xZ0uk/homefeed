import type { APIRequestContext, Page } from "@playwright/test";

import { API_URL } from "./env";
import {
  BIRDWATCHING,
  WOODWORKING,
  apiGet,
  expect,
  open,
  test,
} from "./fixtures";

const [sharpening, workbench] = WOODWORKING.videos;
const [warblers] = BIRDWATCHING.videos;

/** Play a video here, as the watch page reports it (a `play` event). */
async function play(request: APIRequestContext, videoId: string) {
  const response = await request.post(`${API_URL}/watch-events`, {
    data: {
      video_id: videoId,
      event_type: "play",
      position: 0,
      duration: 600,
    },
  });
  expect(response.ok(), `playing ${videoId}`).toBe(true);
}

/** The stored score of a video, or null when it isn't rated. */
async function storedScore(request: APIRequestContext, videoId: string) {
  const { status, body } = await apiGet<{ score: number }>(
    request,
    `/ratings/${videoId}`,
  );
  return status === 404 ? null : body.score;
}

function watchedList(page: Page) {
  return page.getByRole("list", { name: "Watched videos" });
}

/** The history entry whose title is `title`. */
function entry(page: Page, title: string) {
  return watchedList(page)
    .getByRole("listitem")
    .filter({ has: page.getByRole("link", { name: title, exact: true }) });
}

/** The unrated filter's chip, which counts the videos still to rate. */
function unratedChip(page: Page) {
  return page.getByRole("button", { name: /^Unrated/ });
}

test("rate what you watched from the Unrated list", async ({
  page,
  request,
}) => {
  // Watched in this order, so the newest is first: the warblers, the workbench,
  // the plane. The workbench is rated already.
  await play(request, sharpening.id);
  await play(request, workbench.id);
  await play(request, warblers.id);
  const rated = await request.put(`${API_URL}/ratings/${workbench.id}`, {
    data: { score: 6 },
  });
  expect(rated.ok()).toBe(true);

  await open(page, "/history");
  await expect(
    page.getByRole("heading", { name: "History", level: 1 }),
  ).toBeVisible();
  await expect(watchedList(page).getByRole("listitem")).toHaveCount(3);
  // The chip counts the watched videos still to rate.
  const chip = unratedChip(page);
  await expect(chip).toHaveText(/^Unrated\s*2$/);
  await expect(chip).toHaveAttribute("aria-pressed", "false");

  // It lists them, each with a scale of its own.
  await chip.click();
  await expect(page).toHaveURL(/unrated=true/);
  await expect(chip).toHaveAttribute("aria-pressed", "true");
  await expect(watchedList(page).getByRole("listitem")).toHaveCount(2);
  await expect(entry(page, workbench.title)).toHaveCount(0);
  await expect(
    entry(page, warblers.title).getByRole("group", {
      name: `Rate “${warblers.title}”`,
    }),
  ).toBeVisible();
  await expect(page.getByText("Pick a face to rate each video.")).toBeVisible();
  // Nothing has been rated yet, so nothing is announced.
  const rating = page.getByRole("status").filter({ hasText: "Rated" });
  await expect(rating).toHaveCount(0);

  // Rating one saves it and takes it off the list and out of the count.
  await entry(page, warblers.title)
    .getByRole("button", { name: "Great, 8 out of 10" })
    .click();
  await expect(entry(page, warblers.title)).toHaveCount(0);
  await expect(watchedList(page).getByRole("listitem")).toHaveCount(1);
  await expect(chip).toHaveText(/^Unrated\s*1$/);
  await expect(rating).toHaveText(
    `Rated 8 out of 10: ${warblers.title}. 1 left to rate.`,
  );
  await expect.poll(() => storedScore(request, warblers.id)).toBe(8);

  // The last one, by keyboard: arrows move, Enter saves. With nothing left,
  // focus goes to the message so it isn't lost with the row.
  await entry(page, sharpening.title)
    .getByRole("button", { name: "Awful, 1 out of 10" })
    .focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect.poll(() => storedScore(request, sharpening.id)).toBe(2);
  await expect(watchedList(page)).toHaveCount(0);
  await expect(
    page.getByText("You've rated everything you watched."),
  ).toBeVisible();
  await expect(rating).toHaveText(
    `Rated 2 out of 10: ${sharpening.title}. Everything you watched is rated.`,
  );
  await expect(rating).toBeFocused();
  await expect(chip).toHaveText(/^Unrated\s*0$/);

  // Everything is still in the history, with its rating.
  await page.getByRole("link", { name: "Show all history" }).click();
  await expect(page).not.toHaveURL(/unrated/);
  await expect(chip).toHaveAttribute("aria-pressed", "false");
  await expect(watchedList(page).getByRole("listitem")).toHaveCount(3);
  await expect(entry(page, warblers.title)).toContainText("Great, 8 out of 10");
  await expect(entry(page, sharpening.title)).toContainText(
    "Very bad, 2 out of 10",
  );
  await expect(entry(page, workbench.title)).toContainText("Okay, 6 out of 10");
});

test("rating with the keyboard moves on to the next video", async ({
  page,
  request,
}) => {
  await play(request, sharpening.id);
  await play(request, workbench.id);
  await play(request, warblers.id);

  await open(page, "/history?unrated=true");
  await expect(watchedList(page).getByRole("listitem")).toHaveCount(3);

  // The first row: Enter on the third face.
  await entry(page, warblers.title)
    .getByRole("button", { name: "Awful, 1 out of 10" })
    .focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");

  // The scale of the video after it takes focus, ready for the next rating.
  await expect(entry(page, warblers.title)).toHaveCount(0);
  const next = entry(page, workbench.title).getByRole("button", {
    name: "Awful, 1 out of 10",
  });
  await expect(next).toBeFocused();
  await page.keyboard.press("End");
  await page.keyboard.press("Enter");
  await expect(
    entry(page, sharpening.title).getByRole("button", {
      name: "Awful, 1 out of 10",
    }),
  ).toBeFocused();

  await expect.poll(() => storedScore(request, warblers.id)).toBe(3);
  await expect.poll(() => storedScore(request, workbench.id)).toBe(10);
  await expect(unratedChip(page)).toHaveText(/^Unrated\s*1$/);
});

test("with nothing watched, there is nothing to rate", async ({ page }) => {
  await open(page, "/history");
  await expect(
    page.getByText("Nothing here yet. Videos you play show up here."),
  ).toBeVisible();
  const chip = unratedChip(page);
  await expect(chip).toHaveText(/^Unrated\s*0$/);

  await chip.click();
  await expect(page).toHaveURL(/unrated=true/);
  await expect(
    page.getByText("You've rated everything you watched."),
  ).toBeVisible();
  await page.getByRole("link", { name: "Show all history" }).click();
  await expect(page).not.toHaveURL(/unrated/);
});

test("the Unrated filter and the search work together", async ({
  page,
  request,
}) => {
  await play(request, sharpening.id);
  await play(request, workbench.id);
  await play(request, warblers.id);
  const rated = await request.put(`${API_URL}/ratings/${workbench.id}`, {
    data: { score: 6 },
  });
  expect(rated.ok()).toBe(true);

  await open(page, "/history?unrated=true");
  const search = page.getByRole("searchbox", { name: "Search your history" });
  const searchButton = page
    .getByRole("main")
    .getByRole("button", { name: "Search", exact: true });

  // Searching keeps the filter on.
  await search.fill("plane");
  await searchButton.click();
  await expect(page).toHaveURL(/q=plane/);
  await expect(page).toHaveURL(/unrated=true/);
  await expect(watchedList(page).getByRole("listitem")).toHaveCount(1);
  await expect(entry(page, sharpening.title)).toBeVisible();

  // The rated video matches, but isn't unrated: the way out keeps the filter.
  await search.fill("workbench");
  await searchButton.click();
  await expect(
    page.getByText("No unrated videos match “workbench”."),
  ).toBeVisible();
  await page.getByRole("link", { name: "Clear search" }).click();
  await expect(page).toHaveURL(/unrated=true/);
  await expect(page).not.toHaveURL(/q=/);
  await expect(watchedList(page).getByRole("listitem")).toHaveCount(2);

  // Turning the filter off keeps the search.
  await search.fill("workbench");
  await searchButton.click();
  await unratedChip(page).click();
  await expect(page).not.toHaveURL(/unrated/);
  await expect(page).toHaveURL(/q=workbench/);
  await expect(entry(page, workbench.title)).toBeVisible();
});
