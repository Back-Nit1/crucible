import { expect, test } from "@playwright/test";

const sampleEpisode =
  "gen-20261101-p8-t12%3Agenome-0963d13b22fa49e6%3Agen20261101-001";

test("renders the Crucible product shell", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /one request. an auditable decision/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: /no realistic match found/i })).toBeVisible();
  await expect(page).toHaveTitle(/Crucible/);
});

test("keeps sample provenance visible across operational routes", async ({ page }, testInfo) => {
  const routes = [
    ["/world", /evolution, with every denominator/i],
    ["/world/generations", /every evolutionary run/i],
    ["/episodes", /interrogate every decision trace/i],
    [`/episodes/${sampleEpisode}`, /gen-20261101-p8-t12:genome-/i],
    ["/models", /compare contenders/i],
    ["/payments", /mock and sandbox events/i],
    ["/system", /public status view/i],
  ] as const;

  for (const [route, heading] of routes) {
    await page.goto(route);
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    await expect(page.locator("main").getByText(/sample data/i).first()).toBeVisible();
  }

  if (testInfo.project.name === "chromium") {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /one request. an auditable decision/i })).toBeVisible();
    await page.screenshot({ path: "docs/screenshots/agent.png", fullPage: true });
    await page.goto("/world");
    await page.screenshot({ path: "docs/screenshots/world.png", fullPage: true });
    await page.goto("/episodes");
    await expect(page.locator(".ag-root-wrapper")).toBeVisible();
    await page.screenshot({ path: "docs/screenshots/episodes.png", fullPage: true });
    await page.goto("/models");
    await page.screenshot({ path: "docs/screenshots/models.png", fullPage: true });
  }
});

test("mobile navigation is keyboard operable", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "mobile project only");
  await page.goto("/");
  const menu = page.getByRole("button", { name: /open navigation/i });
  await menu.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await expect(page.getByRole("link", { name: "World" })).toBeVisible();
});
