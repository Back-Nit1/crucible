import { expect, test } from "@playwright/test";

test("renders the Crucible product shell", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /one request. an auditable decision/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: /no realistic match found/i })).toBeVisible();
  await expect(page).toHaveTitle(/Crucible/);
});
