import type { APIRequestContext } from "@playwright/test";

import { actionStatus, watch } from "./cards";
import { API_URL } from "./env";
import {
  BIRDWATCHING,
  WOODWORKING,
  apiGet,
  expect,
  feedItem,
  open,
  test,
  withTail,
} from "./fixtures";

/** The day of the feed `fake_api.py` moves back: yesterday's, as "Wed, Oct 14". */
async function yesterday(request: APIRequestContext) {
  const response = await request.post(`${API_URL}/__e2e__/yesterday`);
  expect(response.ok()).toBe(true);
  const { body } = await apiGet<{ date: string }[]>(request, "/feeds");
  return new Date(`${body[0]!.date}T00:00:00Z`).toLocaleDateString("en", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

test("with no feed yet, Today says when the next one comes and offers to build it", async ({
  page,
  request,
}) => {
  await yesterday(request);
  await open(page, "/");

  await expect(
    page.getByRole("heading", { level: 1, name: "Today" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      level: 2,
      name: "There's no feed for today yet.",
    }),
  ).toBeVisible();
  // The daily build is at 6:00 unless set otherwise: today's while it's to come, else tomorrow's.
  await expect(page.getByText(/^Next feed (tomorrow )?at 6:00$/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Build today's feed" }),
  ).toBeVisible();
  // Nothing of a feed is on the page.
  await expect(
    page.getByRole("group", { name: "Filter by intent" }),
  ).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Topics today" })).toHaveCount(
    0,
  );
});

test("it shows what is left unwatched of the last feed, as cards that work", async ({
  page,
  request,
}) => {
  const day = await yesterday(request);
  const [plane, workbench] = WOODWORKING.videos;
  await watch(request, plane.id, 120);
  await open(page, "/");

  const heading = `Still unwatched from ${day}`;
  await expect(
    page.getByRole("heading", { level: 2, name: heading }),
  ).toBeVisible();
  const list = page.getByRole("list", { name: heading });
  // The video I watched is left out.
  await expect(list.getByRole("listitem")).toHaveCount(3);
  await expect(
    list.getByRole("link", { name: plane.title, exact: true }),
  ).toHaveCount(0);
  for (const { title } of [workbench, ...BIRDWATCHING.videos]) {
    await expect(
      list.getByRole("link", { name: title, exact: true }),
    ).toBeVisible();
  }

  // They're ordinary cards: a reason, the quick actions and a menu to dismiss.
  const card = list.getByRole("listitem").filter({
    has: page.getByRole("link", { name: workbench.title, exact: true }),
  });
  await expect(card).toContainText("New from your subscriptions");
  await expect(card.getByRole("button", { name: "Later" })).toBeVisible();
  await card
    .getByRole("button", { name: `More actions for ${workbench.title}` })
    .click();
  await page.getByRole("menuitem", { name: "No reason" }).click();
  await expect(card).toHaveCount(0);
  await expect(list.getByRole("listitem")).toHaveCount(2);
  const status = actionStatus(page, `Dismissed “${workbench.title}”.`);
  await expect(status).toBeVisible();
  await status.getByRole("button", { name: "Undo" }).click();
  await expect(list.getByRole("listitem")).toHaveCount(3);
  await expect(card).toBeVisible();
});

test("it shows the queue, with a button to open it", async ({
  page,
  request,
}) => {
  await yesterday(request);
  await open(page, "/");

  await expect(page.getByText("Nothing in your queue")).toBeVisible();

  const queued = await request.post(`${API_URL}/queue`, {
    data: { video_id: WOODWORKING.videos[0].id },
  });
  expect(queued.ok()).toBe(true);
  await open(page, "/");
  await expect(page.getByText("1 video in your queue")).toBeVisible();
  await page.getByRole("button", { name: "Open queue" }).click();

  const sheet = page.getByRole("dialog", { name: "Queue" });
  await expect(sheet).toBeVisible();
  await expect(sheet).toContainText(WOODWORKING.videos[0].title);
});

test("building the feed from there fills the page", async ({
  page,
  request,
}) => {
  await yesterday(request);
  await open(page, "/");

  await page.getByRole("button", { name: "Build today's feed" }).click();

  await expect(
    page.getByRole("heading", {
      level: 2,
      name: withTail("From your channels", "4 videos"),
    }),
  ).toBeVisible();
  await expect(feedItem(page, WOODWORKING.videos[0].title)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "There's no feed for today yet." }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Topics today" }),
  ).toBeVisible();
});

test("a feed with nothing in it is a page worth opening too", async ({
  page,
  request,
}) => {
  // Nothing left to pick from once no channel is followed (setup stays done).
  expect((await request.post(`${API_URL}/onboarding/complete`)).ok()).toBe(
    true,
  );
  for (const { id } of [WOODWORKING, BIRDWATCHING]) {
    expect((await request.delete(`${API_URL}/channels/${id}`)).ok()).toBe(true);
  }
  expect((await request.post(`${API_URL}/feed/refresh`)).ok()).toBe(true);
  await open(page, "/");

  await expect(
    page.getByRole("heading", {
      level: 2,
      name: "The feed for today is empty.",
    }),
  ).toBeVisible();
  await expect(page.getByText(/^Next feed (tomorrow )?at 6:00$/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Rebuild today's feed" }),
  ).toBeVisible();
  await expect(page.getByText("Nothing in your queue")).toBeVisible();
});
