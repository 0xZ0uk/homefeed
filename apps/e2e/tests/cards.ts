import type { APIRequestContext, Locator, Page } from "@playwright/test";

import { API_URL } from "./env";
import { expect } from "./fixtures";

/** The video `fake_api.py`'s `/__e2e__/outside` adds: from a channel the feed
 * doesn't subscribe to, found as related to a Woodworking video. */
export const OUTSIDE = {
  id: "outs0000001",
  title: "Turning a bowl from a green log",
  channel: "Lathe Works",
} as const;

/** The video `/__e2e__/outside` also adds, for the Discovery carousel: it
 * turns up after the feed was built, so it isn't in the feed. */
export const DISCOVERY = {
  id: "disc0000001",
  title: "Cutting mortises by hand",
} as const;

/** Add the unsubscribed channels' videos, the LLM's scores and a new feed. */
export async function seedOutside(request: APIRequestContext) {
  const response = await request.post(`${API_URL}/__e2e__/outside`);
  expect(response.ok(), "seeding the outside video").toBe(true);
}

/** A button on a feed card by what it says (its name goes on with the title). */
export function cardButton(card: Locator, label: string) {
  return card.getByRole("button", { name: new RegExp(`^${label}`) });
}

/** The status line the feed's actions report to. */
export function actionStatus(page: Page, text: string | RegExp) {
  return page.getByRole("status").filter({ hasText: text });
}

/**
 * Whether `url` calls the web app's server function `name`. They are addressed
 * by the base64 of a JSON naming the file and export they're in.
 */
export function isServerFn(url: URL, name: string): boolean {
  const [, prefix, id] = url.pathname.split("/");
  if (prefix !== "_serverFn" || !id) return false;
  return Buffer.from(id, "base64url").toString().includes(name);
}

/** Record a play (and where it was left) as the player would, as watched. */
export async function watch(
  request: APIRequestContext,
  videoId: string,
  position: number,
  duration = 600,
) {
  for (const [event_type, at] of [
    ["play", 0],
    ["pause", position],
  ] as const) {
    const response = await request.post(`${API_URL}/watch-events`, {
      data: { video_id: videoId, event_type, position: at, duration },
    });
    expect(response.ok(), `recording ${event_type}`).toBe(true);
  }
}
