import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

// DEMO_MODE brand masking is enforced by the API (api/masking.py): it hides `brand` and its occurrences in titles and review text.
// The web app must therefore never add a second, unmasked path to third-party brand marks: no raster/SVG logos, no <img>, no next/image.
function files(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

describe("web brand surfaces", () => {
  const src = files("src").filter((f) => /\.(tsx?|css)$/.test(f) && !f.endsWith(".test.ts") && !f.endsWith(".test.tsx") && !f.includes("/generated/"));

  it("renders no product images or third-party logos", () => {
    const offenders = src.filter((f) => /<img\b|next\/image|<Image\b|url\([^)]*logo/i.test(readFileSync(f, "utf8")));
    expect(offenders).toEqual([]);
  });

  it("has no image assets in the web app", () => {
    const assets = files("public").filter((f) => /\.(png|jpe?g|gif|webp|avif)$/i.test(f));
    expect(assets).toEqual([]);
  });

  it("shows a brand only from the API's own field (null when masked)", () => {
    const card = readFileSync("src/components/agent/product-card.tsx", "utf8");
    expect(card).toContain("product.brand ??");
    expect(card).not.toMatch(/brand:\s*["'][A-Z]/);
  });
});
