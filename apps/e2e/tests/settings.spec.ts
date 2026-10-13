import { apiGet, expect, open, test } from "./fixtures";

interface Settings {
  values: { feed_size: number; timezone: string | null };
  sources: Record<string, string>;
}

test("change settings, then put them back to their defaults", async ({
  page,
  request,
}) => {
  await open(page, "/settings");

  const feed = page.getByRole("region", { name: "Feed", exact: true });
  const size = feed.getByLabel("Videos per day");
  const before = await size.inputValue();
  await size.fill("7");
  await feed.getByRole("button", { name: "Save" }).click();
  await expect(feed.getByRole("status")).toHaveText("Saved.");
  await expect(feed.getByText(`Default: ${before}.`)).toBeVisible();

  const schedule = page.getByRole("region", { name: "Schedule and time zone" });
  const zone = schedule.getByRole("combobox", { name: "Time zone" });
  await zone.fill("Tokyo");
  await page.getByRole("option", { name: "Asia/Tokyo" }).click();
  await schedule.getByRole("button", { name: "Save" }).click();
  await expect(schedule.getByRole("status")).toHaveText("Saved.");

  const { body } = await apiGet<Settings>(request, "/settings");
  expect(body.values).toMatchObject({ feed_size: 7, timezone: "Asia/Tokyo" });
  expect(body.sources.feed_size).toBe("user");

  await feed.getByRole("button", { name: "Reset to default" }).click();
  await expect(size).toHaveValue(before);
  await schedule.getByRole("button", { name: "Reset to default" }).click();
  await expect(zone).toHaveValue(/^System default/);
  const { body: after } = await apiGet<Settings>(request, "/settings");
  expect(after.values.timezone).toBeNull();
  expect(after.sources.feed_size).not.toBe("user");
});

test("an invalid value isn't saved", async ({ page, request }) => {
  await open(page, "/settings");

  const feed = page.getByRole("region", { name: "Feed", exact: true });
  await feed.getByLabel("Discovery slots").fill("500");
  await feed.getByRole("button", { name: "Save" }).click();

  await expect(feed.getByRole("alert")).toHaveText(
    "Discovery slots must be a whole number from 0 to 200.",
  );
  const { body } = await apiGet<Settings>(request, "/settings");
  expect(body.sources.feed_exploration_slots).not.toBe("user");
});

test("the API key is saved but never shown", async ({ page, request }) => {
  await open(page, "/settings");

  const tagging = page.getByRole("region", { name: "Tagging", exact: true });
  await tagging.getByLabel("Tag videos with").selectOption("openrouter");
  await tagging
    .getByLabel("OpenRouter API key")
    .fill("sk-or-v1-e2e-secret-7f3a");
  await tagging.getByRole("button", { name: "Save" }).click();

  await expect(
    tagging.getByText("A key ending in 7f3a is saved", { exact: false }),
  ).toBeVisible();
  await expect(tagging.getByLabel("OpenRouter API key")).toHaveValue("");
  const response = await request.get("/settings");
  expect(await response.text()).not.toContain("e2e-secret");
  const { body } = await apiGet<Settings>(request, "/settings");
  expect(JSON.stringify(body)).not.toContain("e2e-secret");

  await tagging.getByRole("button", { name: "Remove key" }).click();
  await expect(tagging.getByText("Get one at openrouter.ai")).toBeVisible();
});
