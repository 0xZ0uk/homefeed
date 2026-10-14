import { apiGet, expect, open, test } from "./fixtures";

interface Subscription {
  slug: string;
  weight: number;
  hide: boolean;
}

test("muting a tag lists it in the sidebar and can hide its videos", async ({
  page,
  request,
}) => {
  await open(page, "/tags/woodworking");
  const muted = page.getByRole("list", { name: "Muted tags" });
  const subscribed = page.getByRole("list", { name: "Subscribed tags" });
  await expect(muted).toHaveCount(0);

  await page.getByRole("button", { name: "Mute", exact: true }).click();

  // Mute makes a subscription at -0.50; the page offers Unmute and the slider, and
  // the sidebar lists the tag under Muted tags rather than Subscribed tags.
  await expect(page.getByRole("button", { name: "Unmute" })).toBeVisible();
  const slider = page.getByRole("slider", { name: "Weight" });
  await expect(slider).toHaveAttribute("aria-valuetext", "Suppress −0.50");
  await expect(muted.getByRole("link", { name: "woodworking" })).toBeVisible();
  await expect(subscribed).toHaveCount(0);
  expect(
    (await apiGet<Subscription[]>(request, "/tag-subscriptions")).body,
  ).toMatchObject([{ weight: -0.5, hide: false, slug: "woodworking" }]);

  // Hiding is only offered at -1.
  const hide = page.getByRole("checkbox", {
    name: "Hide these videos from my feed",
  });
  await expect(hide).toBeDisabled();
  await slider.focus();
  await slider.press("Home");
  await expect(slider).toHaveAttribute("aria-valuetext", "Suppress −1.00");
  await expect(hide).toBeEnabled();
  await hide.click();
  await expect
    .poll(
      async () =>
        (await apiGet<Subscription[]>(request, "/tag-subscriptions")).body[0]
          ?.hide,
    )
    .toBe(true);
  await expect(hide).toBeChecked();

  // The Tags tab lists it under Muted.
  await open(page, "/subscriptions?tab=tags");
  await page.getByRole("button", { name: "Muted", exact: true }).click();
  const row = page
    .getByRole("list", { name: "Tags", exact: true })
    .getByRole("listitem")
    .filter({ has: page.getByRole("link", { name: "woodworking" }) });
  await expect(row.getByText("Muted", { exact: true })).toBeVisible();
  await expect(
    row.getByRole("button", { name: "Unmute woodworking" }),
  ).toBeVisible();

  // Raising the weight turns hiding off again.
  await open(page, "/tags/woodworking");
  await page.getByRole("slider", { name: "Weight" }).press("ArrowRight");
  await expect
    .poll(
      async () =>
        (await apiGet<Subscription[]>(request, "/tag-subscriptions")).body[0],
    )
    .toMatchObject({ hide: false });
  await expect(hide).toBeDisabled();
  await expect(hide).not.toBeChecked();

  await page.getByRole("button", { name: "Unmute" }).click();
  await expect(page.getByRole("button", { name: "Subscribe" })).toBeVisible();
  await expect(muted).toHaveCount(0);
  expect(
    (await apiGet<Subscription[]>(request, "/tag-subscriptions")).body,
  ).toEqual([]);
});

test("muting a subscribed tag flips it to muted", async ({ page, request }) => {
  await open(page, "/tags/woodworking");
  await page.getByRole("button", { name: "Subscribe" }).click();
  await expect(page.getByRole("button", { name: "Unsubscribe" })).toBeVisible();

  await page.getByRole("button", { name: "Mute", exact: true }).click();

  await expect(page.getByRole("button", { name: "Unmute" })).toBeVisible();
  expect(
    (await apiGet<Subscription[]>(request, "/tag-subscriptions")).body,
  ).toMatchObject([{ weight: -0.5, slug: "woodworking" }]);
});
