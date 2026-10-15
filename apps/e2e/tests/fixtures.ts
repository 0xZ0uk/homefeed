import {
  test as base,
  expect,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

import { API_URL } from "./env";

/** What `fake_api.py` seeds: two subscribed channels and today's feed of their
 * uploads (two per channel), Woodworking first while every prior is neutral. */
export const WOODWORKING = {
  id: `UC${"w".repeat(22)}`,
  title: "Woodworking",
  videos: [
    { id: "wood0000001", title: "Sharpening a hand plane" },
    { id: "wood0000002", title: "Building a workbench" },
  ],
} as const;
export const BIRDWATCHING = {
  id: `UC${"b".repeat(22)}`,
  title: "Birdwatching",
  videos: [
    { id: "bird0000001", title: "Spotting warblers in spring" },
    { id: "bird0000002", title: "Owls at night" },
  ],
} as const;

/** Not subscribed: Woodworking features it, so Discover suggests it once
 * Woodworking is liked (see `likeWoodworking`). */
export const METALWORKING = {
  id: `UC${"m".repeat(22)}`,
  title: "Metalworking",
  videos: [
    { id: "metal000001", title: "Welding aluminium at home" },
    { id: "metal000002", title: "Forging a knife blade" },
    { id: "metal000003", title: "Sharpening a chisel on a stone" },
  ],
} as const;
/** Subscribed only after `resetWith(request, { noisy: true })`: six picks in
 * the feed, none of them watched. */
export const GARDENING = {
  id: `UC${"g".repeat(22)}`,
  title: "Gardening",
} as const;

/** Every test starts from freshly seeded data. */
export const test = base.extend<{ seeded: void }>({
  seeded: [
    async ({ request }, use) => {
      const response = await request.post(`${API_URL}/__e2e__/reset`);
      expect(response.ok(), "resetting the fake API").toBe(true);
      await use();
    },
    { auto: true },
  ],
});

export { expect };

/** Start over from the seed with something extra (see `fake_api.py`). */
export async function resetWith(
  request: APIRequestContext,
  options: { noisy?: boolean },
) {
  const response = await request.post(`${API_URL}/__e2e__/reset`, {
    params: { noisy: options.noisy ?? false },
  });
  expect(response.ok(), "resetting the fake API").toBe(true);
}

/** Love Woodworking, so Discover suggests the channels it features. */
export async function likeWoodworking(request: APIRequestContext) {
  const response = await request.patch(
    `${API_URL}/channels/${WOODWORKING.id}`,
    {
      data: { prior: "love" },
    },
  );
  expect(response.ok(), "loving Woodworking").toBe(true);
}

/**
 * Open `path` and wait until React has hydrated the page, so clicks and
 * selections reach their handlers (server-rendered controls are inert before).
 */
export async function open(page: Page, path: string) {
  await page.goto(path);
  await waitForHydration(page);
}

/** Wait until every control on the page has React's event props attached. */
export async function waitForHydration(page: Page) {
  await page.waitForFunction(() => {
    const controls = document.querySelectorAll(
      "main button, main select, main input, main a",
    );
    return (
      controls.length > 0 &&
      [...controls].every((el) =>
        Object.keys(el).some((key) => key.startsWith("__reactProps$")),
      )
    );
  });
}

/**
 * Today's feed, as the ordered lists on the home page: one for each lane, "New
 * to you" and "From your channels" (a lane with no videos has no list). Look
 * for a card or count them across both; the lists are two, so a visibility
 * check wants `.first()`.
 */
export function feedList(page: Page) {
  return page.getByRole("list", { name: /^(New to you|From your channels)$/ });
}

/**
 * A name made of a label and words only a screen reader gets, in a visually
 * hidden tail ("New to you" and ", 4 videos"). Playwright reads the tail with a
 * space before it, which a browser's accessibility tree may not have.
 */
export function withTail(label: string, tail: string): RegExp {
  const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`^${escape(label)} ?, ${escape(tail)}$`);
}

/** The feed entry whose title is `title`. */
export function feedItem(page: Page, title: string) {
  return feedList(page)
    .getByRole("listitem")
    .filter({ has: page.getByRole("link", { name: title, exact: true }) });
}

/** Read the API directly (bypassing the web app), to check what was saved. */
export async function apiGet<T>(
  request: APIRequestContext,
  path: string,
): Promise<{ status: number; body: T }> {
  const response = await request.get(`${API_URL}${path}`);
  return { status: response.status(), body: (await response.json()) as T };
}
