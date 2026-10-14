import { API_URL } from "./env";
import {
  WOODWORKING,
  apiGet,
  expect,
  feedItem,
  open,
  test,
  waitForHydration,
} from "./fixtures";

interface Onboarding {
  completed: boolean;
  subscribed_channels: number;
  needed: boolean;
}

// A fresh install: no subscriptions, no feed, setup not done.
test.beforeEach(async ({ request }) => {
  const response = await request.post(`${API_URL}/__e2e__/reset?fresh=true`);
  expect(response.ok(), "resetting the fake API").toBe(true);
});

test("a fresh install is sent to setup, which ends in a first feed", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await expect(page).toHaveURL("/welcome");
  await waitForHydration(page);
  await expect(
    page.getByRole("heading", { name: "Welcome", level: 1 }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Get started" }).click();
  // Focus follows to the new step's heading.
  const heading = page.getByRole("heading", { name: "Add channels", level: 1 });
  await expect(heading).toBeFocused();

  await page.getByLabel("Channel name").fill("woodworking");
  await page.getByRole("button", { name: "Search" }).click();
  await page
    .getByRole("list", { name: "Search results" })
    .getByRole("button", { name: `Subscribe to ${WOODWORKING.title}` })
    .click();

  await expect(page.getByRole("status").first()).toHaveText(
    `Subscribed to ${WOODWORKING.title}.`,
  );
  await expect(
    page
      .getByRole("list", { name: "Your channels" })
      .getByText(WOODWORKING.title),
  ).toBeVisible();

  await page.getByRole("button", { name: "Next" }).click();
  await expect(
    page.getByRole("heading", { name: "Build your feed", level: 1 }),
  ).toBeFocused();
  await page.getByRole("button", { name: "Build my feed" }).click();

  await expect(page).toHaveURL("/");
  await expect(feedItem(page, WOODWORKING.videos[0].title)).toBeVisible();
  expect((await apiGet<Onboarding>(request, "/onboarding")).body).toEqual({
    completed: true,
    subscribed_channels: 1,
    needed: false,
  });
});

test("a channel link can be pasted", async ({ page }) => {
  await open(page, "/welcome");
  await page.getByRole("button", { name: "Get started" }).click();
  await page
    .getByLabel("Paste a channel link")
    .fill("https://www.youtube.com/@wood");
  await page.getByRole("button", { name: "Subscribe", exact: true }).click();
  await expect(
    page
      .getByRole("list", { name: "Your channels" })
      .getByText(WOODWORKING.title),
  ).toBeVisible();
});

test("skipping setup goes home and stays skipped", async ({
  page,
  request,
}) => {
  await open(page, "/welcome");
  await page.getByRole("button", { name: "Skip setup" }).click();

  await expect(page).toHaveURL("/");
  await expect(
    page.getByText("There's no feed for today yet."),
  ).toBeVisible();
  expect((await apiGet<Onboarding>(request, "/onboarding")).body.needed).toBe(
    false,
  );

  // No redirect any more, and other pages were never redirected.
  await page.goto("/");
  await expect(page).toHaveURL("/");
});

test("other pages are not redirected during setup", async ({ page }) => {
  await open(page, "/history");
  await expect(page).toHaveURL("/history");
});
