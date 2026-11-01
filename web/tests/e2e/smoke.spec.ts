import { expect, test } from "@playwright/test";

test("renders the Crucible product shell", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /trust is earned in the trace/i })).toBeVisible();
  await expect(page).toHaveTitle(/Crucible/);
});
