import { expect, test as setup } from "@playwright/test";

import { APP_PASSWORD, AUTH_FILE } from "./env";

// Log in once and share the session cookie with every test.
setup("log in", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Password").fill(APP_PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("heading", { name: /^Today/ })).toBeVisible();
  await page.context().storageState({ path: AUTH_FILE });
});
