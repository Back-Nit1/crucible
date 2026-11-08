import sample from "@/generated/snapshot-sample.json";
import { generationSnapshotSchema } from "@/lib/api/schemas";
import { BUDGET, buildLayout, ringRadius, selectRendered, writePositions } from "./motion";

const snapshot = generationSnapshotSchema.parse(sample.body);

describe("motion engine", () => {
  it("budget constants are exact", () => {
    expect(BUDGET).toEqual({
      MAX_SHOPPERS: 2500,
      MAX_PRODUCT_INSTANCES: 3000,
      MAX_LABELS: 40,
      MAX_DPR: 1.5,
    });
  });

  it("selectRendered caps and is deterministic", () => {
    const many = Array.from({ length: 5000 }, (_, i) => ({ id: `ep-${i}` }));
    const a = selectRendered(many);
    expect(a).toHaveLength(2500);
    expect(selectRendered([...many].reverse().reverse())).toEqual(a);
    expect([...a].sort((x, y) => x - y)).toEqual(a);
  });

  it("selectRendered returns all when under budget", () => {
    expect(selectRendered(snapshot.episodes)).toHaveLength(snapshot.episodes.length);
  });

  it("positions are finite and stay near their world", () => {
    const layout = buildLayout(snapshot);
    const rendered = selectRendered(snapshot.episodes);
    const out = new Float32Array(rendered.length * 3);
    const limit = ringRadius(snapshot.categories.length) + 4;
    for (const t of [0, 3.7, 100]) {
      writePositions(snapshot, layout, rendered, t, out);
      rendered.forEach((episodeIndex, i) => {
        const world = snapshot.episodes[episodeIndex]!.world;
        const dx = out[i * 3]! - layout.worldCenters[world * 3]!;
        const dz = out[i * 3 + 2]! - layout.worldCenters[world * 3 + 2]!;
        expect(Number.isFinite(out[i * 3 + 1]!)).toBe(true);
        expect(Math.hypot(dx, dz)).toBeLessThanOrEqual(limit);
      });
    }
  });

  it("product instances never exceed budget", () => {
    const layout = buildLayout(snapshot, 5);
    expect(layout.productSlots.size).toBeLessThanOrEqual(5);
    expect(layout.productPositions.length).toBe(layout.productSlots.size * 3);
    expect(buildLayout(snapshot).productSlots.size).toBeLessThanOrEqual(BUDGET.MAX_PRODUCT_INSTANCES);
  });
});
