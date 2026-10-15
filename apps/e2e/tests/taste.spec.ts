import type { APIRequestContext, Page } from "@playwright/test";

import { actionStatus } from "./cards";
import { API_URL } from "./env";
import {
  METALWORKING,
  apiGet,
  expect,
  open,
  resetWith,
  test,
} from "./fixtures";

interface Subscription {
  slug: string;
  weight: number;
  hide: boolean;
}

async function send(
  request: APIRequestContext,
  method: "post" | "put" | "patch",
  path: string,
  data?: object,
) {
  const response = await request[method](
    `${API_URL}${path}`,
    data ? { data } : undefined,
  );
  expect(response.ok(), `${method.toUpperCase()} ${path}`).toBe(true);
}

/** The weight of the tag's subscription, or undefined when it has none. */
async function weightOf(request: APIRequestContext, slug: string) {
  const { body } = await apiGet<Subscription[]>(request, "/tag-subscriptions");
  return body.find((subscription) => subscription.slug === slug)?.weight;
}

/**
 * The noisy seed has eleven picks, six of them Gardening's uploads. Tag those
 * six, follow Gardening at +0.80, follow Woodworking (two picks carry it) and
 * Metalworking (none do) at +0.50, and mute Welding.
 */
async function seedTopics(request: APIRequestContext) {
  await resetWith(request, { noisy: true });
  for (let n = 1; n <= 6; n += 1) {
    await send(
      request,
      "post",
      `/videos/gard${String(n).padStart(7, "0")}/tags`,
      { label: "Gardening" },
    );
  }
  await send(request, "post", "/tags/gardening/subscribe");
  await send(request, "patch", "/tags/gardening/subscription", { weight: 0.8 });
  await send(request, "post", "/tags/woodworking/subscribe");
  await send(request, "post", "/tags/metalworking/subscribe");
  await send(request, "post", "/tags/welding/mute");
}

function followed(page: Page, label: string) {
  return page
    .getByRole("list", { name: "Followed topics" })
    .getByRole("listitem")
    .filter({ has: page.getByRole("link", { name: label, exact: true }) });
}

function muted(page: Page, label: string) {
  return page
    .getByRole("list", { name: "Muted topics" })
    .getByRole("listitem")
    .filter({ has: page.getByRole("link", { name: label, exact: true }) });
}

test("Taste is a page of You, and sums up what the feed believes in a few sentences", async ({
  page,
  request,
}) => {
  await seedTopics(request);
  await open(page, "/you");

  const card = page
    .getByRole("main")
    .getByRole("link", { name: "Taste", exact: true });
  await expect(card).toBeVisible();
  await card.click();
  await expect(page).toHaveURL("/taste");
  await expect(
    page.getByRole("heading", { level: 1, name: "Your taste" }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Main" })
      .getByRole("list", { name: "In You" })
      .getByRole("link", { name: "Taste" }),
  ).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("heading", { level: 2 })).toHaveText([
    "Topics",
    "Channels",
    "Signals",
    "Model",
  ]);

  // The sentences are made from the numbers below them.
  await expect(page.getByText(/^You love Gardening/)).toHaveText(
    "You love Gardening, and you've muted welding. Gardening takes 55% of your picks, while metalworking is followed but rarely shows up: no picks in the last 30 days. You haven't rated any videos yet; the model starts training at 20.",
  );

  // Most picked first. Gardening takes most of the picks, Metalworking none.
  const rows = page
    .getByRole("list", { name: "Followed topics" })
    .getByRole("listitem");
  await expect(rows.getByRole("link")).toHaveText([
    "Gardening",
    "woodworking",
    "metalworking",
  ]);
  const gardening = followed(page, "Gardening");
  await expect(gardening).toContainText(
    "55% of your picks · Watched 0 of 6 picks · no ratings yet",
  );
  await expect(gardening).toContainText("Takes 55% of your picks.");
  await expect(
    gardening.getByRole("button", { name: "Lower boost to +0.50" }),
  ).toBeVisible();
  const woodworking = followed(page, "woodworking");
  await expect(woodworking).toContainText("18% of your picks");
  await expect(woodworking).toContainText("Watched 0 of 2 picks");
  await expect(woodworking.getByText(/Takes|Rarely/)).toHaveCount(0);
  const metalworking = followed(page, "metalworking");
  await expect(metalworking).toContainText(
    "Rarely shows up: no picks in the last 30 days.",
  );
  await expect(
    metalworking.getByRole("button", { name: "Raise boost to +0.80" }),
  ).toBeVisible();

  // Muted topics are listed apart.
  await expect(muted(page, "welding")).toContainText("Suppress −0.50");
  await expect(
    muted(page, "welding").getByRole("button", { name: "Unmute welding" }),
  ).toBeVisible();
});

test("a boost is changed from its slider or from a suggestion, and each change can be undone", async ({
  page,
  request,
}) => {
  await seedTopics(request);
  await open(page, "/taste");
  const gardening = followed(page, "Gardening");
  const slider = page.getByRole("slider", { name: "Boost for Gardening" });
  await expect(slider).toHaveAttribute("aria-valuetext", "Boost +0.80");

  // The slider saves when let go, and says what it did.
  await slider.focus();
  await slider.press("ArrowLeft");
  await expect(slider).toHaveAttribute("aria-valuetext", "Boost +0.75");
  await expect(
    actionStatus(
      page,
      "Set the boost of Gardening to +0.75. The next feed uses it.",
    ),
  ).toBeVisible();
  await expect.poll(() => weightOf(request, "gardening")).toBe(0.75);

  // Undo puts it back, and the slider follows.
  const status = page.getByRole("status").filter({ hasText: "Gardening" });
  await status.getByRole("button", { name: "Undo" }).click();
  await expect(actionStatus(page, "Restored Gardening.")).toBeVisible();
  await expect.poll(() => weightOf(request, "gardening")).toBe(0.8);
  await expect(slider).toHaveAttribute("aria-valuetext", "Boost +0.80");

  // A topic that takes most of the picks gets a click to lower its boost.
  await gardening.getByRole("button", { name: "Lower boost to +0.50" }).click();
  await expect(
    actionStatus(
      page,
      "Set the boost of Gardening to +0.50. The next feed uses it.",
    ),
  ).toBeVisible();
  await expect.poll(() => weightOf(request, "gardening")).toBe(0.5);
  await expect(slider).toHaveAttribute("aria-valuetext", "Boost +0.50");
  // It can go lower still, and the suggestion says where.
  await expect(
    gardening.getByRole("button", { name: "Lower boost to +0.20" }),
  ).toBeVisible();

  // Moving the slider again straight away is saved too, and keeps the focus.
  await slider.focus();
  await slider.press("ArrowRight");
  await slider.press("ArrowRight");
  await expect(slider).toBeFocused();
  await expect(slider).toHaveAttribute("aria-valuetext", "Boost +0.60");
  await expect.poll(() => weightOf(request, "gardening")).toBe(0.6);

  // One that hardly shows up gets a click to raise it.
  const metalworking = followed(page, "metalworking");
  await metalworking
    .getByRole("button", { name: "Raise boost to +0.80" })
    .click();
  await expect.poll(() => weightOf(request, "metalworking")).toBe(0.8);
  await expect(
    metalworking.getByRole("slider", { name: "Boost for metalworking" }),
  ).toHaveAttribute("aria-valuetext", "Boost +0.80");
  await page.getByRole("status").getByRole("button", { name: "Undo" }).click();
  await expect.poll(() => weightOf(request, "metalworking")).toBe(0.5);
});

test("a topic is muted, unfollowed and unmuted from its row, and each can be undone", async ({
  page,
  request,
}) => {
  await seedTopics(request);
  await send(request, "patch", "/tags/woodworking/subscription", {
    weight: 0.65,
  });
  await open(page, "/taste");

  // Mute moves the topic to the muted list.
  await followed(page, "woodworking")
    .getByRole("button", { name: "Mute woodworking" })
    .click();
  const mutedStatus = actionStatus(
    page,
    "Muted woodworking. It's in your muted topics now.",
  );
  await expect(mutedStatus).toBeVisible();
  // The row the press was on is gone, so focus goes to the message.
  await expect(mutedStatus).toBeFocused();
  await expect(followed(page, "woodworking")).toHaveCount(0);
  await expect(muted(page, "woodworking")).toContainText("Suppress −0.50");
  await expect.poll(() => weightOf(request, "woodworking")).toBe(-0.5);

  // Undo brings it back at the boost it had.
  await mutedStatus.getByRole("button", { name: "Undo" }).click();
  await expect(actionStatus(page, "Restored woodworking.")).toBeVisible();
  await expect(muted(page, "woodworking")).toHaveCount(0);
  await expect(followed(page, "woodworking")).toBeVisible();
  await expect.poll(() => weightOf(request, "woodworking")).toBe(0.65);

  // Unfollow removes it.
  await followed(page, "metalworking")
    .getByRole("button", { name: "Unfollow metalworking" })
    .click();
  const unfollowed = actionStatus(page, "Unfollowed metalworking.");
  await expect(unfollowed).toBeFocused();
  await expect(followed(page, "metalworking")).toHaveCount(0);
  expect(await weightOf(request, "metalworking")).toBeUndefined();
  await unfollowed.getByRole("button", { name: "Undo" }).click();
  await expect(followed(page, "metalworking")).toBeVisible();
  await expect.poll(() => weightOf(request, "metalworking")).toBe(0.5);

  // Unmute removes the mute, and Undo mutes it again.
  await muted(page, "welding")
    .getByRole("button", { name: "Unmute welding" })
    .click();
  const unmuted = actionStatus(page, "Unmuted welding.");
  await expect(unmuted).toBeFocused();
  await expect(page.getByRole("list", { name: "Muted topics" })).toHaveCount(0);
  expect(await weightOf(request, "welding")).toBeUndefined();
  await unmuted.getByRole("button", { name: "Undo" }).click();
  await expect(muted(page, "welding")).toBeVisible();
  await expect.poll(() => weightOf(request, "welding")).toBe(-0.5);
});

test("a change that fails says what to do and leaves the topic as it was", async ({
  page,
  request,
}) => {
  await seedTopics(request);
  await open(page, "/taste");

  // Stand in for the API being down: the server functions fail.
  await page.route("**/_serverFn/**", (route) => route.abort());
  await followed(page, "metalworking")
    .getByRole("button", { name: "Mute metalworking" })
    .click();
  const failure = actionStatus(page, "Couldn't mute metalworking. Try again.");
  await expect(failure).toBeVisible();
  // Nothing to undo, and the row is still where it was, ready to try again.
  await expect(failure.getByRole("button", { name: "Undo" })).toHaveCount(0);
  await expect(followed(page, "metalworking")).toBeVisible();
  await expect(
    followed(page, "metalworking").getByRole("button", {
      name: "Mute metalworking",
    }),
  ).toBeEnabled();

  await page.unroute("**/_serverFn/**");
  await followed(page, "metalworking")
    .getByRole("button", { name: "Mute metalworking" })
    .click();
  await expect(muted(page, "metalworking")).toBeVisible();
  await expect.poll(() => weightOf(request, "metalworking")).toBe(-0.5);
});

test("a boost dragged below zero mutes the topic", async ({
  page,
  request,
}) => {
  await seedTopics(request);
  await open(page, "/taste");

  const slider = page.getByRole("slider", { name: "Boost for metalworking" });
  await slider.focus();
  await slider.press("Home");
  await expect(actionStatus(page, "Muted metalworking (−1.00).")).toBeVisible();
  await expect(followed(page, "metalworking")).toHaveCount(0);
  await expect(muted(page, "metalworking")).toContainText("Suppress −1.00");
  await expect.poll(() => weightOf(request, "metalworking")).toBe(-1);

  await page.getByRole("status").getByRole("button", { name: "Undo" }).click();
  await expect(followed(page, "metalworking")).toBeVisible();
  await expect.poll(() => weightOf(request, "metalworking")).toBe(0.5);
});

test("channels you rate well but don't follow can be subscribed to or tried", async ({
  page,
  request,
}) => {
  const [first, second] = METALWORKING.videos;
  await send(request, "put", `/ratings/${first.id}`, { score: 9 });
  await send(request, "put", `/ratings/${second.id}`, { score: 8 });
  await open(page, "/taste");

  const channels = page.getByRole("region", { name: "Channels" });
  // Both channels are on the default preference, which the page points out.
  await expect(channels.locator("dd")).toHaveText(["0", "0", "2", "0"]);
  await expect(
    channels.getByText(
      "All 2 of your channels are still on Neutral, the default",
    ),
  ).toBeVisible();
  await expect(
    channels.getByRole("link", { name: "Open Subscriptions" }),
  ).toHaveAttribute("href", "/subscriptions");

  const list = channels.getByRole("list", {
    name: "Channels rated well, not followed",
  });
  const row = list.getByRole("listitem");
  await expect(row).toHaveCount(1);
  await expect(row).toContainText(METALWORKING.title);
  await expect(row).toContainText("avg 8.5 from 2 ratings");

  // A trial subscribes for two weeks, and can be taken back.
  await row
    .getByRole("button", { name: `Try for 2 weeks: ${METALWORKING.title}` })
    .click();
  const trial = actionStatus(
    page,
    `Started a 2-week trial of ${METALWORKING.title}.`,
  );
  await expect(trial).toBeFocused();
  await expect(list).toHaveCount(0);
  const channelsList = await apiGet<
    { channel_id: string; trial_until: string | null }[]
  >(request, "/channels");
  expect(
    channelsList.body.find((channel) => channel.channel_id === METALWORKING.id)
      ?.trial_until,
  ).not.toBeNull();
  await trial.getByRole("button", { name: "Undo" }).click();
  await expect(
    actionStatus(page, `Unsubscribed from ${METALWORKING.title}.`),
  ).toBeVisible();
  await expect(row).toHaveCount(1);

  // Subscribing is a plain subscription, and Undo takes it back too.
  await row
    .getByRole("button", { name: `Subscribe to ${METALWORKING.title}` })
    .click();
  const subscribed = actionStatus(page, `Subscribed to ${METALWORKING.title}.`);
  await expect(subscribed).toBeFocused();
  await expect(list).toHaveCount(0);
  // It is among the followed now: three channels, all on Neutral.
  await expect(channels.locator("dd")).toHaveText(["0", "0", "3", "0"]);
  await expect(
    channels.getByText("All 3 of your channels are still on Neutral"),
  ).toBeVisible();
  await subscribed.getByRole("button", { name: "Undo" }).click();
  await expect(row).toHaveCount(1);
  const after = await apiGet<{ channel_id: string }[]>(request, "/channels");
  expect(after.body.map((channel) => channel.channel_id)).not.toContain(
    METALWORKING.id,
  );
});

test("signals count your ratings, feedback and dismissals, each with what it does", async ({
  page,
  request,
}) => {
  const feed = await apiGet<{ items: { id: number; video_id: string }[] }>(
    request,
    "/feed/today",
  );
  const [first, second, third] = feed.body.items;
  expect(third).toBeDefined();
  await send(request, "put", `/ratings/${first?.video_id}`, { score: 8 });
  await send(request, "post", "/watch-events", {
    video_id: second?.video_id,
    event_type: "play",
    position: 5,
    duration: 600,
  });
  await send(request, "put", `/videos/${first?.video_id}/feedback`, {
    signal: 1,
  });
  await send(request, "put", `/videos/${second?.video_id}/feedback`, {
    signal: -1,
  });
  await send(request, "post", `/feed-items/${third?.id}/dismiss`, {
    reason: "Clickbait",
  });
  await open(page, "/taste");

  const signals = page.getByRole("region", { name: "Signals" });
  const signal = (title: string) =>
    signals.getByRole("listitem").filter({
      has: page.getByRole("heading", { level: 3, name: title }),
    });
  const ratings = signal("Ratings");
  await expect(ratings).toContainText("1");
  await expect(ratings).toContainText("50% of the 2 videos you've watched");
  await expect(ratings).toContainText(
    "Ratings train the model, set each channel's score",
  );
  await expect(signal("More like this")).toContainText("1");
  await expect(signal("More like this")).toContainText(
    "Pushes videos like these up",
  );
  await expect(signal("Less like this")).toContainText("1");
  await expect(signal("Less like this")).toContainText(
    "Pushes videos like these down",
  );
  const dismissed = signal("Dismissed in the last 30 days");
  await expect(
    dismissed.getByRole("list", { name: "Dismissals by reason" }),
  ).toContainText("Clickbait");
  await expect(dismissed).toContainText("A dismissed video never comes back");

  // Fewer than the model needs: it says how far along the ratings are.
  await expect(page.getByRole("region", { name: "Model" })).toContainText(
    "No model yet: until there are enough ratings, the feed is ranked by your subscriptions and topics. You have 1 of the 20 it needs to start.",
  );
  await expect(
    page.getByRole("region", { name: "Model" }).getByRole("link", {
      name: "Open Models",
    }),
  ).toHaveAttribute("href", "/models");
});

test("a fresh install gets a place to begin, not empty boxes", async ({
  page,
  request,
}) => {
  const response = await request.post(`${API_URL}/__e2e__/reset?fresh=true`);
  expect(response.ok(), "resetting the fake API").toBe(true);
  await open(page, "/taste");

  await expect(
    page.getByRole("heading", { level: 1, name: "Your taste" }),
  ).toBeVisible();
  await expect(
    page.getByText(/^Homefeed doesn't know your taste yet\./),
  ).toHaveText(
    "Homefeed doesn't know your taste yet. Follow a few topics and rate what you watch, and this page will show what it learns.",
  );
  const topics = page.getByRole("region", { name: "Topics" });
  await expect(topics).toContainText("You don't follow any topics yet.");
  await expect(
    topics.getByRole("link", { name: "browse all the tags" }),
  ).toHaveAttribute("href", "/subscriptions?tab=tags");
  const channels = page.getByRole("region", { name: "Channels" });
  await expect(channels).toContainText("You don't follow any channels yet.");
  await expect(channels.getByRole("link", { name: "Discover" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Signals" })).toContainText(
    "You haven't rated a video yet.",
  );
  await expect(page.getByRole("region", { name: "Model" })).toContainText(
    "No model yet: until there are enough ratings, the feed is ranked by your subscriptions and topics. You have 0 of the 20 it needs to start.",
  );
});
