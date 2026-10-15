import type { APIRequestContext, Page, Route } from "@playwright/test";

import { API_URL } from "./env";
import { BIRDWATCHING, WOODWORKING, expect, open, test } from "./fixtures";

const [sharpening, workbench] = WOODWORKING.videos;
const dovetails = { id: "wood0000003", title: "Cutting dovetails by hand" };
const [warblers, owls] = BIRDWATCHING.videos;

/**
 * Embed the workbench video and some others at given similarities to it (a
 * cosine of 0.3 or less counts as unrelated), and record the plane video as
 * what YouTube suggests next to it. Only the dovetails and the plane qualify.
 */
async function seedSimilar(request: APIRequestContext) {
  const response = await request.post(`${API_URL}/__e2e__/similar`, {
    data: {
      seed: workbench.id,
      similarities: {
        [dovetails.id]: 0.9,
        [sharpening.id]: 0.7,
        [warblers.id]: 0.1,
      },
      related: [sharpening.id],
    },
  });
  expect(response.ok(), "seeding similar videos").toBe(true);
}

/** Make the similar videos' server function fail, until the returned function runs. */
async function failSimilarVideos(page: Page) {
  const handler = async (route: Route) => {
    const id = new URL(route.request().url()).pathname.split("/").pop() ?? "";
    const name = Buffer.from(decodeURIComponent(id), "base64").toString();
    if (name.includes("fetchSimilarVideos")) await route.abort();
    else await route.fallback();
  };
  await page.route("**/_serverFn/**", handler);
  return () => page.unroute("**/_serverFn/**", handler);
}

function moreLikeThis(page: Page) {
  return page.getByRole("region", { name: "More like this" });
}

test("find more like this only when asked", async ({ page, request }) => {
  await seedSimilar(request);
  await open(page, `/watch/${workbench.id}`);

  // Nothing is offered until it is asked for.
  const section = moreLikeThis(page);
  await expect(
    section.getByRole("heading", { name: "More like this", level: 2 }),
  ).toBeVisible();
  await expect(
    section.getByText("Similar videos only appear when you ask for them."),
  ).toBeVisible();
  await expect(section.getByRole("list")).toHaveCount(0);

  const ask = section.getByRole("button", { name: "Find more like this" });
  await ask.click();

  // A finite list, the closest first, each saying why it is there. The video
  // below the similarity floor is left out.
  const cards = section
    .getByRole("list", { name: "Videos like this one" })
    .getByRole("listitem");
  await expect(cards).toHaveCount(2);
  await expect(cards.nth(0)).toContainText(dovetails.title);
  await expect(cards.nth(0)).toContainText("Similar to this video");
  await expect(cards.nth(1)).toContainText(sharpening.title);
  await expect(cards.nth(1)).toContainText("Related on YouTube");
  await expect(section.getByText(warblers.title)).toHaveCount(0);

  // The button leaves with the answer; the message that replaces it has focus.
  const status = section.getByRole("status");
  await expect(status).toHaveText("Found 2 videos like this one.");
  await expect(status).toBeFocused();
  await expect(ask).toHaveCount(0);

  // A card leads to its watch page, which offers nothing until asked either.
  await cards.nth(0).getByRole("link", { name: dovetails.title }).click();
  await expect(page).toHaveURL(`/watch/${dovetails.id}`);
  await expect(
    page.getByRole("heading", { name: dovetails.title, level: 1 }),
  ).toBeVisible();
  await expect(moreLikeThis(page).getByRole("list")).toHaveCount(0);
  await expect(
    moreLikeThis(page).getByRole("button", { name: "Find more like this" }),
  ).toBeVisible();
});

test("nothing similar yet, until videos are analysed", async ({ page }) => {
  // Nothing was embedded in this database.
  await open(page, `/watch/${owls.id}`);

  const section = moreLikeThis(page);
  await section.getByRole("button", { name: "Find more like this" }).click();

  const status = section.getByRole("status");
  await expect(status).toHaveText(
    "Nothing similar yet. Similar videos show up once videos are analysed.",
  );
  await expect(status).toBeFocused();
  await expect(section.getByRole("list")).toHaveCount(0);
});

test("a failed search says so and can be tried again", async ({
  page,
  request,
}) => {
  await seedSimilar(request);
  await open(page, `/watch/${workbench.id}`);
  const restore = await failSimilarVideos(page);

  const section = moreLikeThis(page);
  await section.getByRole("button", { name: "Find more like this" }).click();

  await expect(section.getByRole("alert")).toHaveText(
    "Couldn't load similar videos. Try again in a moment.",
  );
  await expect(section.getByRole("list")).toHaveCount(0);
  const again = section.getByRole("button", { name: "Try again" });
  await expect(again).toBeVisible();

  await restore();
  await again.click();
  await expect(
    section
      .getByRole("list", { name: "Videos like this one" })
      .getByRole("listitem"),
  ).toHaveCount(2);
  await expect(section.getByRole("alert")).toHaveCount(0);
});
