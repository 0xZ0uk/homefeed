import { WOODWORKING, apiGet, expect, feedItem, open, test } from "./fixtures";
import { actionStatus, cardButton, watch } from "./cards";

const video = WOODWORKING.videos[0];
const other = WOODWORKING.videos[1];

/** The video's stored score, or null when it isn't rated. */
async function stored(request: Parameters<typeof apiGet>[0]) {
  const { status, body } = await apiGet<{ score: number }>(
    request,
    `/ratings/${video.id}`,
  );
  return status === 404 ? null : body.score;
}

test("a watched card says so, shows how far you got, and can be rated on the spot", async ({
  page,
  request,
}) => {
  await watch(request, video.id, 300);
  await open(page, "/");
  const card = feedItem(page, video.title);

  // Watched in words (not just a faded card), with a bar for how far you got.
  await expect(card.getByText("Watched")).toContainText("Watched, 50% of it");
  await expect(card).toHaveCSS("opacity", "1");
  // Cards of videos you haven't watched offer no rating.
  await expect(feedItem(page, other.title)).not.toContainText("Watched");
  await expect(cardButton(feedItem(page, other.title), "Rate it")).toHaveCount(
    0,
  );

  await cardButton(card, "Rate it").click();
  const scale = page.getByRole("group", { name: `Rate “${video.title}”` });
  await scale.getByRole("button", { name: "Great, 8 out of 10" }).click();

  await expect(cardButton(card, "You rated it 8")).toBeVisible();
  await expect(
    actionStatus(page, `Rated “${video.title}”: Great, 8 out of 10.`),
  ).toBeVisible();
  await expect.poll(() => stored(request)).toBe(8);

  // Undo takes the rating back.
  await actionStatus(page, "Rated")
    .getByRole("button", { name: "Undo" })
    .click();
  await expect(cardButton(card, "Rate it")).toBeVisible();
  await expect(actionStatus(page, "Undone.")).toBeVisible();
  await expect.poll(() => stored(request)).toBeNull();
});

test("a rating given on a card can be changed there", async ({
  page,
  request,
}) => {
  await watch(request, video.id, 300);
  await open(page, "/");
  const card = feedItem(page, video.title);

  await cardButton(card, "Rate it").click();
  await page
    .getByRole("group", { name: `Rate “${video.title}”` })
    .getByRole("button", { name: "Good, 7 out of 10" })
    .click();
  await expect(cardButton(card, "You rated it 7")).toBeVisible();

  await cardButton(card, "You rated it 7").click();
  await page
    .getByRole("group", { name: `Rate “${video.title}”` })
    .getByRole("button", { name: "Poor, 4 out of 10" })
    .click();

  await expect(cardButton(card, "You rated it 4")).toBeVisible();
  await expect.poll(() => stored(request)).toBe(4);

  // It's the rating the watch page shows, too.
  await card.getByRole("link", { name: video.title }).click();
  await expect(page).toHaveURL(`/watch/${video.id}`);
  await expect(
    page
      .getByRole("group", { name: "Rate this video" })
      .getByRole("button", { name: "Poor, 4 out of 10" }),
  ).toHaveAttribute("aria-pressed", "true");
});
