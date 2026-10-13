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

/** Today's feed, as the ordered list on the home page. */
export function feedList(page: Page) {
  return page.getByRole("list", { name: "Feed" });
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
