import type { APIRequestContext, Page } from "@playwright/test";

import { watch } from "./cards";
import { API_URL } from "./env";
import {
  BIRDWATCHING,
  METALWORKING,
  apiGet,
  expect,
  open,
  test,
} from "./fixtures";

interface Channel {
  channel_id: string;
  trial_until: string | null;
}
interface Hide {
  channel_id: string;
  kind: string;
}

const [welding] = METALWORKING.videos;
const [warblers, owls] = BIRDWATCHING.videos;

/** The page's recap of the week's discoveries. */
function recap(page: Page) {
  return page.getByRole("region", { name: "Discoveries" });
}

/** The row of the channel titled `title` in one of the recap's lists. */
function row(page: Page, list: string, title: string) {
  return recap(page)
    .getByRole("list", { name: list, exact: true })
    .getByRole("listitem")
    .filter({ hasText: title });
}

/** A line of the page's live regions that says `text`. */
function said(page: Page, text: string | RegExp) {
  return page.getByRole("status").filter({ hasText: text });
}

/** One of the totals, by its label. */
function total(page: Page, label: string) {
  return recap(page).locator("dl").filter({ hasText: label });
}

/** Play a video as it was `daysAgo` days back. */
async function watchedDaysAgo(
  request: APIRequestContext,
  videoId: string,
  daysAgo: number,
) {
  const response = await request.post(`${API_URL}/__e2e__/watch`, {
    data: { video_id: videoId, days_ago: daysAgo },
  });
  expect(response.ok(), `playing ${videoId}`).toBe(true);
}

async function rate(
  request: APIRequestContext,
  videoId: string,
  score: number,
) {
  const response = await request.put(`${API_URL}/ratings/${videoId}`, {
    data: { score },
  });
  expect(response.ok(), `rating ${videoId}`).toBe(true);
}

test("a channel watched for the first time shows up with where it stands and its topics", async ({
  page,
  request,
}) => {
  // Metalworking isn't followed; Birdwatching is.
  await watch(request, welding.id, 120);
  await rate(request, welding.id, 8);
  await watch(request, warblers.id, 60);

  await open(page, "/insights");

  await expect(
    page.getByRole("heading", { level: 2, name: "Discoveries" }),
  ).toBeVisible();
  await expect(recap(page)).toContainText(
    "You tried 2 new channels this week (0 last week) and kept 1.",
  );
  // The best rated first; what was watched and how it was rated; where it stands.
  const channels = recap(page)
    .getByRole("list", { name: "New channels", exact: true })
    .getByRole("listitem");
  await expect(channels).toHaveCount(2);
  await expect(channels.first()).toContainText(METALWORKING.title);
  const metal = row(page, "New channels", METALWORKING.title);
  await expect(metal).toContainText("1 video watched · rated 8");
  await expect(metal).toContainText("Not followed");
  await expect(
    metal.getByRole("link", { name: METALWORKING.title }),
  ).toHaveAttribute("href", `/channels/${METALWORKING.id}`);
  const birds = row(page, "New channels", BIRDWATCHING.title);
  await expect(birds).toContainText("1 video watched · not rated");
  await expect(birds).toContainText("Subscribed");

  // The totals, each beside last week's.
  await expect(total(page, "New channels tried")).toContainText("2");
  await expect(total(page, "New channels tried")).toContainText("0 last week");
  await expect(total(page, "Channels kept")).toContainText("1");
  await expect(total(page, "Channels rated 7 or higher")).toContainText("1");
  await expect(total(page, "Videos from new channels")).toContainText("100%");

  // The topics of what was watched, each a link to its tag.
  const topics = recap(page).getByRole("list", {
    name: "New topics",
    exact: true,
  });
  await expect(
    topics.getByRole("link", { name: "welding", exact: true }),
  ).toHaveAttribute("href", "/tags/welding");
  await expect(
    topics.getByRole("link", { name: "metalworking", exact: true }),
  ).toBeVisible();

  // The rest of the page is still there.
  await expect(
    page.getByRole("heading", { level: 2, name: /^This week/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { level: 2, name: "Good rate by week" }),
  ).toBeVisible();
});

test("sets the week against the one before", async ({ page, request }) => {
  // Birdwatching was first watched ten days ago, so it was last week's find.
  await watchedDaysAgo(request, warblers.id, 10);
  await watchedDaysAgo(request, owls.id, 2);
  await watch(request, welding.id, 120);

  await open(page, "/insights");

  await expect(recap(page)).toContainText(
    "You tried 1 new channel this week (1 last week) and haven't kept it yet.",
  );
  await expect(
    recap(page).getByRole("list", { name: "New channels", exact: true }),
  ).toHaveCount(1);
  await expect(row(page, "New channels", BIRDWATCHING.title)).toHaveCount(0);
  await expect(row(page, "New channels", METALWORKING.title)).toBeVisible();
  // One of the two videos watched this week came from a new channel; last
  // week's only one did.
  const share = total(page, "Videos from new channels");
  await expect(share).toContainText("50%");
  await expect(share).toContainText("1 of 2 videos · 100% last week");
  await expect(share).toContainText("−50 pts");
  const tried = total(page, "New channels tried");
  await expect(tried).toContainText("1 last week");
});

test("a week without anything new says where to look", async ({ page }) => {
  await open(page, "/insights");

  await expect(recap(page)).toContainText(
    "You didn't try any new channels this week or last week.",
  );
  await expect(
    recap(page).getByRole("link", { name: "Discover" }),
  ).toHaveAttribute("href", "/discover");
  await expect(
    recap(page).getByRole("link", { name: "Today" }),
  ).toHaveAttribute("href", "/");
  // Nothing to compare, list or follow up.
  await expect(recap(page).getByText("New channels tried")).toHaveCount(0);
  await expect(recap(page).getByRole("list")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { level: 2, name: /^This week/ }),
  ).toBeVisible();
});

test("try a channel for two weeks from the follow-ups, then undo it", async ({
  page,
  request,
}) => {
  await watch(request, welding.id, 120);
  await rate(request, welding.id, 8);
  await open(page, "/insights");
  const worth = recap(page).getByRole("list", {
    name: "Worth following",
    exact: true,
  });
  const metal = worth.getByRole("listitem");
  await expect(metal).toContainText(METALWORKING.title);
  await expect(metal).toContainText("Best rating: Great, 8 out of 10");
  await expect(
    metal.getByRole("button", { name: `Subscribe to ${METALWORKING.title}` }),
  ).toBeVisible();

  await metal
    .getByRole("button", { name: `Try for 2 weeks: ${METALWORKING.title}` })
    .click();

  const started = said(page, "Started a 2-week trial of Metalworking");
  await expect(started).toBeVisible();
  await expect(started).toBeFocused();
  await expect(
    started.getByRole("link", { name: "Open Subscriptions" }),
  ).toHaveAttribute("href", "/subscriptions");
  // No longer worth following; in the list of new channels, on trial.
  await expect(worth).toHaveCount(0);
  await expect(recap(page)).toContainText("Nothing to follow up right now.");
  await expect(row(page, "New channels", METALWORKING.title)).toContainText(
    "On trial · 14 days left",
  );
  const trial = await apiGet<Channel[]>(request, "/channels");
  const days =
    (Date.parse(
      trial.body.find((c) => c.channel_id === METALWORKING.id)?.trial_until ??
        "",
    ) -
      Date.now()) /
    86_400_000;
  expect(days).toBeGreaterThan(13.9);
  expect(days).toBeLessThan(14.1);
  await expect(recap(page)).toContainText(
    "You tried 1 new channel this week (0 last week) and kept it.",
  );

  await started.getByRole("button", { name: "Undo" }).click();

  const undone = said(page, "Unsubscribed from Metalworking.");
  await expect(undone).toBeVisible();
  await expect(undone).toBeFocused();
  await expect(worth.getByRole("listitem")).toContainText(METALWORKING.title);
  await expect(row(page, "New channels", METALWORKING.title)).toContainText(
    "Not followed",
  );
  const after = await apiGet<Channel[]>(request, "/channels");
  expect(after.body.map((c) => c.channel_id)).not.toContain(METALWORKING.id);
});

test("subscribing from the follow-ups can be undone, and puts a hide back", async ({
  page,
  request,
}) => {
  const hidden = await request.put(
    `${API_URL}/channels/${METALWORKING.id}/hide`,
    { data: { kind: "blocked" } },
  );
  expect(hidden.ok(), "hiding Metalworking").toBe(true);
  await watch(request, welding.id, 120);
  await rate(request, welding.id, 9);
  await open(page, "/insights");
  await expect(row(page, "New channels", METALWORKING.title)).toContainText(
    "Hidden",
  );
  const worth = row(page, "Worth following", METALWORKING.title);
  await expect(worth).toContainText("Hidden from feed and Discover");

  await worth
    .getByRole("button", { name: `Subscribe to ${METALWORKING.title}` })
    .click();

  const subscribed = said(page, "Subscribed to Metalworking.");
  await expect(subscribed).toBeVisible();
  await expect(worth).toHaveCount(0);
  await expect(row(page, "New channels", METALWORKING.title)).toContainText(
    "Subscribed",
  );
  const followed = await apiGet<Channel[]>(request, "/channels");
  expect(followed.body.map((c) => c.channel_id)).toContain(METALWORKING.id);
  // Subscribing clears the hide.
  expect((await apiGet<Hide[]>(request, "/channel-hides")).body).toEqual([]);

  await subscribed.getByRole("button", { name: "Undo" }).click();

  await expect(said(page, "Unsubscribed from Metalworking.")).toBeVisible();
  await expect(worth).toBeVisible();
  await expect(row(page, "New channels", METALWORKING.title)).toContainText(
    "Hidden",
  );
  const after = await apiGet<Channel[]>(request, "/channels");
  expect(after.body.map((c) => c.channel_id)).not.toContain(METALWORKING.id);
  // The channel is hidden as it was before.
  expect((await apiGet<Hide[]>(request, "/channel-hides")).body).toMatchObject([
    { channel_id: METALWORKING.id, kind: "blocked" },
  ]);
});
