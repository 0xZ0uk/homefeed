import {
  BIRDWATCHING,
  apiGet,
  expect,
  open,
  waitForHydration,
  feedList,
  test,
} from "./fixtures";

interface Channel {
  channel_id: string;
  prior: string;
}

test("edit a channel preference and see it in the feed", async ({
  page,
  request,
}) => {
  await open(page, "/subscriptions");

  const row = page
    .getByRole("list", { name: "Subscriptions" })
    .getByRole("listitem")
    .filter({ hasText: BIRDWATCHING.title });
  const preference = row.getByLabel("Preference");
  await expect(preference).toHaveValue("neutral");

  await preference.selectOption({ label: "Love" });
  await expect(preference).toHaveValue("love");
  await expect
    .poll(async () => {
      const { body } = await apiGet<Channel[]>(request, "/channels");
      return body.find((c) => c.channel_id === BIRDWATCHING.id)?.prior;
    })
    .toBe("love");
  await page.reload();
  await waitForHydration(page);
  await expect(row.getByLabel("Preference")).toHaveValue("love");

  // A refreshed feed now leads with the loved channel's uploads.
  await open(page, "/");
  await expect(feedList(page).first()).toBeVisible();
  await page.getByRole("button", { name: "Refresh feed" }).click();
  await expect(feedList(page).getByRole("listitem").first()).toContainText(
    BIRDWATCHING.title,
  );
});
