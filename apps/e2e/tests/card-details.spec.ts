import {
  BIRDWATCHING,
  WOODWORKING,
  expect,
  feedItem,
  open,
  test,
} from "./fixtures";
import { OUTSIDE, cardButton, seedOutside } from "./cards";

const [plane, workbench] = WOODWORKING.videos;

test("a card says why it's there, and pressing the reason shows the score breakdown", async ({
  page,
}) => {
  await open(page, "/");
  const card = feedItem(page, plane.title);

  // The reason is on the card itself, not behind a hover.
  await expect(card).toContainText("New from your subscriptions");
  await cardButton(card, "Why this is here").click();

  const details = page.getByRole("dialog", { name: "Why this is here" });
  await expect(details).toBeVisible();
  await expect(details).toContainText("New from your subscriptions");
  await expect(
    details.getByRole("heading", { name: "Score breakdown" }),
  ).toBeVisible();
  await expect(details.getByRole("row", { name: /^Channel/ })).toBeVisible();
  await expect(details.getByRole("row", { name: /^Score/ })).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(details).toBeHidden();
  await expect(cardButton(card, "Why this is here")).toBeFocused();
});

test("a card shows its length and its tags, which lead to their pages", async ({
  page,
}) => {
  await open(page, "/");
  const card = feedItem(page, workbench.title);

  // The length on the thumbnail, in words for a screen reader.
  await expect(card).toContainText("11 min");
  await expect(card).toContainText(WOODWORKING.title);
  // Its tags, most confident first, after the title's own link.
  await expect(card.getByRole("link")).toHaveText([
    workbench.title,
    "#workbench",
    "#woodworking",
    "#hand tools",
  ]);
  // A video without tags has no chips to link to.
  await expect(
    feedItem(page, BIRDWATCHING.videos[0].title).getByRole("link"),
  ).toHaveCount(1);

  await card.getByRole("link", { name: "woodworking", exact: true }).click();
  await expect(page).toHaveURL("/tags/woodworking");
});

test("a video from a channel you don't follow says so, and flags what the tagger thinks of it", async ({
  page,
  request,
}) => {
  await seedOutside(request);
  await open(page, "/");

  // Its lane says it's new to you, so the card doesn't say it again.
  const outside = page
    .getByRole("list", { name: "New to you" })
    .getByRole("listitem")
    .filter({ has: page.getByRole("link", { name: OUTSIDE.title }) });
  await expect(outside).toBeVisible();
  await expect(outside).not.toContainText("New to you");
  await expect(outside).toContainText("Related to “Sharpening a hand plane”");
  await expect(outside).toContainText(OUTSIDE.channel);
  await expect(outside).toContainText("1 h 9 min");
  // Clickbait comes with an icon, not just words.
  const flag = outside.getByText("Likely clickbait");
  await expect(flag).toBeVisible();
  await expect(flag.locator("svg")).toBeVisible();
  await expect(outside).not.toContainText("Deep dive");

  // A subscribed channel's in-depth video is flagged the other way round.
  const subscribed = feedItem(page, workbench.title);
  await expect(subscribed).toContainText("Deep dive");
  await expect(subscribed.getByText("Deep dive").locator("svg")).toBeVisible();
  await expect(subscribed).not.toContainText("New to you");
  await expect(subscribed).not.toContainText("Likely clickbait");
  await expect(feedItem(page, plane.title)).not.toContainText("New to you");
});
