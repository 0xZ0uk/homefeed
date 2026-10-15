import { apiGet, expect, open, test } from "./fixtures";

interface Subscription {
  slug: string;
  weight: number;
}

test("subscribing on a tag page lists the tag under Explore", async ({
  page,
  request,
}) => {
  // Explore lists the tags you follow.
  const yourTags = page.getByRole("list", { name: "Subscribed tags" });
  await open(page, "/explore");
  await expect(
    page.getByText("You haven't followed or muted any tags"),
  ).toBeVisible();
  await expect(yourTags).toHaveCount(0);

  await open(page, "/tags/woodworking");
  await page.getByRole("button", { name: "Subscribe" }).click();

  // The button turns into Unsubscribe next to the weight slider, at +0.50.
  await expect(page.getByRole("button", { name: "Unsubscribe" })).toBeVisible();
  const slider = page.getByRole("slider", { name: "Weight" });
  await expect(slider).toHaveAttribute("aria-valuetext", "Boost +0.50");
  expect(
    (await apiGet<Subscription[]>(request, "/tag-subscriptions")).body,
  ).toMatchObject([{ weight: 0.5, slug: "woodworking" }]);

  // Letting go of the slider saves the new weight.
  await slider.press("ArrowRight");
  await expect(slider).toHaveAttribute("aria-valuetext", "Boost +0.55");
  await expect
    .poll(
      async () =>
        (await apiGet<Subscription[]>(request, "/tag-subscriptions")).body[0]
          ?.weight,
    )
    .toBeCloseTo(0.55);

  // Explore lists it and leads back to the tag, and the subscription survives
  // a reload.
  await open(page, "/explore");
  await yourTags.getByRole("link", { name: "woodworking" }).click();
  await expect(page).toHaveURL("/tags/woodworking");
  await page.reload();
  await expect(page.getByRole("button", { name: "Unsubscribe" })).toBeVisible();

  // The Tags tab marks it as subscribed, with its weight.
  await open(page, "/subscriptions?tab=tags");
  const row = page
    .getByRole("list", { name: "Tags", exact: true })
    .getByRole("listitem")
    .filter({ has: page.getByRole("link", { name: "woodworking" }) });
  await expect(row.getByText("Subscribed", { exact: true })).toBeVisible();
  await expect(row.getByText(/Boost \+0\.55/)).toBeVisible();
  await expect(
    row.getByRole("button", { name: "Unsubscribe from woodworking" }),
  ).toBeVisible();

  await open(page, "/tags/woodworking");
  await page.getByRole("button", { name: "Unsubscribe" }).click();
  await expect(page.getByRole("button", { name: "Subscribe" })).toBeVisible();
  expect(
    (await apiGet<Subscription[]>(request, "/tag-subscriptions")).body,
  ).toEqual([]);
  await open(page, "/explore");
  await expect(
    page.getByText("You haven't followed or muted any tags"),
  ).toBeVisible();
  await expect(yourTags).toHaveCount(0);
});
