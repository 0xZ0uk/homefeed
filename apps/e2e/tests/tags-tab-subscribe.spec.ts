import { apiGet, expect, open, test } from "./fixtures";

interface Subscription {
  slug: string;
  weight: number;
}

test("subscribe to a tag in one click from the Tags tab", async ({
  page,
  request,
}) => {
  await open(page, "/subscriptions?tab=tags");
  const list = page.getByRole("list", { name: "Tags", exact: true });
  const row = (label: string) =>
    list
      .getByRole("listitem")
      .filter({ has: page.getByRole("link", { name: label, exact: true }) });

  // Search narrows the list; each tag offers Subscribe.
  await page.getByRole("searchbox", { name: "Search tags" }).fill("wo");
  await expect(row("woodworking")).toBeVisible();
  await expect(row("hand tools")).toHaveCount(0);

  await row("woodworking")
    .getByRole("button", { name: "Subscribe to woodworking" })
    .click();

  // The row shows it as subscribed and offers Unsubscribe.
  const unsubscribe = row("woodworking").getByRole("button", {
    name: "Unsubscribe from woodworking",
  });
  await expect(unsubscribe).toBeVisible();
  await expect(
    row("woodworking").getByText("Subscribed", { exact: true }),
  ).toBeVisible();
  expect(
    (await apiGet<Subscription[]>(request, "/tag-subscriptions")).body,
  ).toMatchObject([{ slug: "woodworking", weight: 0.5 }]);

  // The Subscribed filter shows only the subscribed tags.
  await page.getByRole("searchbox", { name: "Search tags" }).fill("");
  await page.getByRole("button", { name: "Subscribed", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Subscribed", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(row("workbench")).toHaveCount(0);
  await expect(row("woodworking")).toBeVisible();

  // Unsubscribing takes it out of the filtered list and the API.
  await unsubscribe.click();
  await expect(
    page.getByText("You haven't subscribed to any tags yet."),
  ).toBeVisible();
  expect(
    (await apiGet<Subscription[]>(request, "/tag-subscriptions")).body,
  ).toEqual([]);

  // Back on All, the tag offers Subscribe again.
  await page.getByRole("button", { name: "All", exact: true }).click();
  await expect(
    row("woodworking").getByRole("button", {
      name: "Subscribe to woodworking",
    }),
  ).toBeVisible();
});
