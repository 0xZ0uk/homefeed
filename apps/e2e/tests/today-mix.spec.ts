import type { APIRequestContext, Locator, Page } from "@playwright/test";

import { API_URL } from "./env";
import {
  WOODWORKING,
  apiGet,
  expect,
  feedItem,
  open,
  test,
  withTail,
} from "./fixtures";

const workbench = WOODWORKING.videos[1];

interface Settings {
  values: {
    feed_size: number;
    feed_exploration_slots: number;
    feed_max_topic_share: number;
  };
  sources: Record<string, string>;
}

/** The strip under Today's header: the topics and the Rebalance button. */
function strip(page: Page) {
  return page.getByRole("region", { name: "Topics today" });
}

/** The topics in the strip, each a link to its tag. */
function topics(page: Page) {
  return strip(page).getByRole("list", { name: "Top topics today" });
}

/** Open the Rebalance popover. */
async function rebalance(page: Page) {
  await strip(page).getByRole("button", { name: "Rebalance" }).click();
  const panel = page.getByRole("dialog", { name: "Rebalance your feed" });
  await expect(panel).toBeVisible();
  return panel;
}

/**
 * Choose one of the dial's options as a person does, by its words: the radio
 * itself is visually hidden, and the label around it is what is pressed.
 */
async function choose(scope: Locator, option: string) {
  await scope.getByText(option, { exact: true }).click();
}

async function settings(request: APIRequestContext) {
  return (await apiGet<Settings>(request, "/settings")).body;
}

test("the strip names what today's picks are about, with how many carry each", async ({
  page,
}) => {
  await open(page, "/");

  // Only one of the first picks has tags; each topic counts it once.
  const links = topics(page).getByRole("link");
  await expect(links).toHaveCount(3);
  for (const [label, slug] of [
    ["hand tools", "hand-tools"],
    ["woodworking", "woodworking"],
    ["workbench", "workbench"],
  ] as const) {
    await expect(
      topics(page).getByRole("link", { name: withTail(label, "1 pick") }),
    ).toHaveAttribute("href", `/tags/${slug}`);
  }

  // "Show more" adds a second woodworking pick, which makes it the top topic.
  await page.getByRole("button", { name: "Show more" }).click();
  await expect(links.first()).toHaveAccessibleName(
    withTail("woodworking", "2 picks"),
  );
  await expect(links).toHaveCount(3);

  await links.first().click();
  await expect(page).toHaveURL("/tags/woodworking");
});

test("dismissed picks leave the strip", async ({ page }) => {
  await open(page, "/");
  await expect(topics(page).getByRole("link")).toHaveCount(3);

  await feedItem(page, workbench.title)
    .getByRole("button", { name: `More actions for ${workbench.title}` })
    .click();
  await page.getByRole("menuitem", { name: "No reason" }).click();

  await expect(feedItem(page, workbench.title)).toHaveCount(0);
  await expect(topics(page)).toHaveCount(0);
  await expect(strip(page)).toContainText("No topics yet");
});

test("the dial saves a mix of discovery slots and topic share", async ({
  page,
  request,
}) => {
  await open(page, "/");
  // The seed has no discovery slots, which none of the choices is.
  await expect(strip(page)).toContainText("Mix: Custom");
  const panel = await rebalance(page);
  const dial = panel.getByRole("radiogroup", { name: "Mix" });
  await expect(dial.getByRole("radio")).toHaveCount(3);
  await expect(dial.getByRole("radio", { checked: true })).toHaveCount(0);
  await expect(dial).toContainText(
    "Custom: 0 discovery slots, and no topic takes more than 40% of the feed.",
  );
  await expect(panel.getByText("Applies to the next feed.")).toHaveCount(0);

  await choose(dial, "Adventurous");

  await expect(dial.getByRole("radio", { name: "Adventurous" })).toBeChecked();
  await expect(dial).toContainText(
    "6 discovery slots, and no topic takes more than 25% of the feed.",
  );
  await expect(strip(page)).toContainText("Mix: Adventurous");
  // It's saved as settings, which the Settings page also edits.
  await expect
    .poll(async () => (await settings(request)).values)
    .toMatchObject({
      feed_exploration_slots: 6,
      feed_max_topic_share: 0.25,
    });
  expect((await settings(request)).sources).toMatchObject({
    feed_exploration_slots: "user",
    feed_max_topic_share: "user",
  });

  await choose(dial, "Familiar");
  await expect(strip(page)).toContainText("Mix: Familiar");
  await expect
    .poll(async () => (await settings(request)).values)
    .toMatchObject({
      feed_exploration_slots: 1,
      feed_max_topic_share: 0.6,
    });
  await choose(dial, "Balanced");
  await expect(strip(page)).toContainText("Mix: Balanced");
  await expect
    .poll(async () => (await settings(request)).values)
    .toMatchObject({
      feed_exploration_slots: 3,
      feed_max_topic_share: 0.4,
    });

  // The choice is still there on a reload.
  await open(page, "/");
  await expect(strip(page)).toContainText("Mix: Balanced");
  const again = await rebalance(page);
  await expect(again.getByRole("radio", { name: "Balanced" })).toBeChecked();
});

test("the dial holds the discovery slots to the size of the feed", async ({
  page,
  request,
}) => {
  const response = await request.patch(`${API_URL}/settings`, {
    data: { set: { feed_size: 4 } },
  });
  expect(response.ok()).toBe(true);
  await open(page, "/");

  const panel = await rebalance(page);
  await choose(panel, "Adventurous");

  // Six slots won't fit in four videos, so it saves four; that's still Adventurous.
  await expect
    .poll(async () => (await settings(request)).values.feed_exploration_slots)
    .toBe(4);
  expect((await settings(request)).values.feed_max_topic_share).toBe(0.25);
  await expect(panel).toContainText(
    "4 discovery slots, and no topic takes more than 25% of the feed.",
  );
  await open(page, "/");
  await expect(strip(page)).toContainText("Mix: Adventurous");
});

test("settings that match no choice are Custom, with a way to Settings", async ({
  page,
  request,
}) => {
  const response = await request.patch(`${API_URL}/settings`, {
    data: { set: { feed_exploration_slots: 5, feed_max_topic_share: 0.3 } },
  });
  expect(response.ok()).toBe(true);
  await open(page, "/");

  await expect(strip(page)).toContainText("Mix: Custom");
  const panel = await rebalance(page);
  await expect(panel.getByRole("radio", { checked: true })).toHaveCount(0);
  await expect(panel).toContainText(
    "Custom: 5 discovery slots, and no topic takes more than 30% of the feed.",
  );
  await panel.getByRole("link", { name: "Change it in Settings" }).click();
  await expect(page).toHaveURL("/settings");
});

test("a changed mix applies to the next feed, which can be built from the popover", async ({
  page,
  request,
}) => {
  await open(page, "/");
  const before = (await apiGet<{ id: number }>(request, "/feed/today")).body.id;
  const panel = await rebalance(page);
  // The popover's own status comes first; the rebuild button has one too.
  const note = panel.getByRole("status").first();
  // A live region, on the page and empty before there is anything to say.
  await expect(note).toHaveText("");

  await choose(panel, "Balanced");

  await expect(note).toHaveText("Applies to the next feed.");
  const build = panel.getByRole("button", { name: "Rebuild today's feed" });
  await build.click();

  // The feed was built again, and the note goes: the change is in it now.
  await expect
    .poll(
      async () =>
        (await apiGet<{ id: number }>(request, "/feed/today")).body.id,
    )
    .toBeGreaterThan(before);
  await expect(panel.getByText("Applies to the next feed.")).toHaveCount(0);
  await expect(build).toHaveCount(0);
});

test("the popover has a slider for each topic I follow, which applies to the next feed too", async ({
  page,
  request,
}) => {
  const followed = await request.post(`${API_URL}/tags/woodworking/subscribe`);
  expect(followed.ok()).toBe(true);
  await open(page, "/");

  const panel = await rebalance(page);
  const list = panel.getByRole("list", { name: "Followed topics" });
  // Named with how many of today's picks carry it.
  const slider = list.getByRole("slider", { name: "woodworking · 1 today" });
  await expect(slider).toHaveAttribute("aria-valuetext", "Boost +0.50");

  await slider.press("ArrowLeft");
  await expect(slider).toHaveAttribute("aria-valuetext", "Boost +0.45");
  await expect
    .poll(
      async () =>
        (
          await apiGet<{ slug: string; weight: number }[]>(
            request,
            "/tag-subscriptions",
          )
        ).body[0]?.weight,
    )
    .toBeCloseTo(0.45);
  // (Each slider's value is a status too, hence the filter.)
  await expect(
    panel.getByRole("status").filter({ hasText: "Applies to the next feed." }),
  ).toBeVisible();
});

test("with no followed topics, the popover says how to follow one", async ({
  page,
}) => {
  await open(page, "/");

  const panel = await rebalance(page);

  await expect(panel).toContainText("You don't follow any topics yet.");
  await panel
    .getByRole("link", { name: "browse your tags in Explore" })
    .click();
  await expect(page).toHaveURL("/explore");
});
