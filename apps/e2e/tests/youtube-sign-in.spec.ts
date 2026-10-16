import { apiGet, expect, open, test } from "./fixtures";

interface Settings {
  values: { ytdlp_cookies_from_browser: string | null };
}

const FIREFOX = "firefox:/home/e2e/.mozilla/firefox/e2e.default";

test("YouTube's bot check points to the sign-in setting, which takes a browser", async ({
  page,
  request,
}) => {
  await open(page, "/watch/botcheck001");
  const alert = page.getByRole("alert");
  await expect(alert).toContainText("confirm it's not a bot");
  await expect(alert).not.toContainText("--cookies-from-browser");
  await alert.getByRole("link", { name: "Use your YouTube sign-in" }).click();

  await expect(page).toHaveURL(/\/settings#youtube-sign-in-heading$/);
  const section = page.getByRole("region", { name: "YouTube sign-in" });
  const browser = section.getByLabel("Use YouTube cookies from");
  await expect(browser).toHaveValue("");
  await browser.selectOption({ label: "Firefox (default-release)" });
  await section.getByRole("button", { name: "Check" }).click();
  await expect(section.getByRole("status").first()).toHaveText(
    "Signed in to YouTube. Homefeed can use these cookies.",
  );
  await section.getByRole("button", { name: "Save" }).click();
  await expect(section.getByText("Saved.")).toBeVisible();

  const { body } = await apiGet<Settings>(request, "/settings");
  expect(body.values.ytdlp_cookies_from_browser).toBe(FIREFOX);

  await section.getByRole("button", { name: "Reset to default" }).click();
  await expect(browser).toHaveValue("");
});

test("another browser is typed in, and one that can't be read says why", async ({
  page,
  request,
}) => {
  await open(page, "/settings");
  const section = page.getByRole("region", { name: "YouTube sign-in" });
  await section
    .getByLabel("Use YouTube cookies from")
    .selectOption({ label: "Another browser…" });
  const other = section.getByLabel("Browser and profile");
  await section.getByRole("button", { name: "Save" }).click();
  await expect(section.getByRole("alert")).toHaveText(
    "Type a browser, or choose one from the list.",
  );
  await expect(other).toBeFocused();

  await other.fill("chrome:Profile 2");
  await section.getByRole("button", { name: "Check" }).click();
  await expect(section.getByRole("status").first()).toContainText(
    "Couldn't read the browser's cookies",
  );

  await other.fill("netscape");
  await section.getByRole("button", { name: "Save" }).click();
  await expect(section.getByRole("alert")).toContainText(
    "yt-dlp can't read cookies from 'netscape'",
  );
  const { body } = await apiGet<Settings>(request, "/settings");
  expect(body.values.ytdlp_cookies_from_browser).toBeNull();
});
