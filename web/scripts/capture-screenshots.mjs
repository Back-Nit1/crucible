// Live-mode screenshots of our own UI (never sample mode). Needs the web app and API already running:
//   NEXT_PUBLIC_DATA_MODE=live; run from web/: node scripts/capture-screenshots.mjs http://127.0.0.1:3100
import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";

const base = process.argv[2] ?? "http://127.0.0.1:3100";
const out = new URL("../../docs/screenshots/", import.meta.url).pathname;
await mkdir(out, { recursive: true });
const routes = [["home", "/"], ["world", "/world"], ["episodes", "/episodes"], ["models", "/models"], ["payments", "/payments"], ["system", "/system"]];
const browser = await chromium.launch();
for (const [name, path] of routes) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(base + path, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500); // AG Grid renders rows after hydration
  await page.screenshot({ path: `${out}${name}.png`, fullPage: false });
  const sample = await page.getByText(/sample data/i).count();
  console.log(name, path, sample ? "WARNING: sample-mode label visible" : "live");
  await page.close();
}
const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true });
await mobile.goto(base + "/", { waitUntil: "networkidle" });
await mobile.waitForTimeout(1000);
await mobile.screenshot({ path: `${out}mobile-home.png` });
await browser.close();
