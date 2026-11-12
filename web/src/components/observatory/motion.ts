import type { GenerationSnapshot } from "@/lib/api/types";

/** Hard limits for a MacBook-class GPU. Everything rendered is capped by these, never by data size. */
export const BUDGET = {
  MAX_SHOPPERS: 2500,
  MAX_PRODUCT_INSTANCES: 3000,
  MAX_LABELS: 40,
  MAX_DPR: 1.5,
} as const;

export const HOP_SECONDS = 1.2;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

type Snapshot = GenerationSnapshot;
type Stop = [number, number];

export type Layout = {
  ringRadius: number;
  worldCenters: Float32Array; // xyz per world
  shopOffsets: Float32Array; // xyz per category, relative to its world centre
  productSlots: Map<string, number>; // `${world}:${product}` -> product instance index
  productPositions: Float32Array; // xyz per product instance
};

export function fnv1a(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h;
}

export function ringRadius(categoryCount: number): number {
  return Math.max(3, categoryCount * 0.45);
}

/** Indices of the episodes to draw: all under budget, else the same deterministic subset every load. */
export function selectRendered(
  episodes: readonly { id: string }[],
  max: number = BUDGET.MAX_SHOPPERS,
): number[] {
  const all = episodes.map((_, i) => i);
  if (episodes.length <= max) return all;
  return all
    .sort((a, b) => fnv1a(episodes[a]!.id) - fnv1a(episodes[b]!.id) || a - b)
    .slice(0, max)
    .sort((a, b) => a - b);
}

export function buildLayout(
  snapshot: Snapshot,
  maxProducts: number = BUDGET.MAX_PRODUCT_INSTANCES,
): Layout {
  const radius = ringRadius(snapshot.categories.length);
  const spacing = radius * 2 + 4; // worlds never overlap, whatever the category count
  const worldCenters = new Float32Array(snapshot.worlds.length * 3);
  snapshot.worlds.forEach((_, i) => {
    const r = spacing * Math.sqrt(i) * 0.75;
    worldCenters[i * 3] = Math.cos(i * GOLDEN_ANGLE) * r;
    worldCenters[i * 3 + 2] = Math.sin(i * GOLDEN_ANGLE) * r;
  });

  const n = Math.max(1, snapshot.categories.length);
  const shopOffsets = new Float32Array(snapshot.categories.length * 3);
  snapshot.categories.forEach((_, c) => {
    const angle = (c / n) * Math.PI * 2 - Math.PI / 2;
    shopOffsets[c * 3] = Math.cos(angle) * radius;
    shopOffsets[c * 3 + 2] = Math.sin(angle) * radius;
  });

  const catIndex = new Map(snapshot.categories.map((c, i) => [c.id, i]));
  const productSlots = new Map<string, number>();
  const positions: number[] = [];
  for (const e of selectRendered(snapshot.episodes)) {
    const episode = snapshot.episodes[e]!;
    for (const [kind, ref] of episode.path) {
      const key = `${episode.world}:${ref}`;
      if (kind !== 3 || productSlots.has(key) || productSlots.size >= maxProducts) continue;
      const product = snapshot.products[ref];
      const c = product ? (catIndex.get(product.category) ?? 0) : 0;
      const angle = (fnv1a(product?.id ?? key) % 360) * (Math.PI / 180);
      const spread = 0.6 + (fnv1a(key) % 60) / 100;
      productSlots.set(key, productSlots.size);
      positions.push(
        worldCenters[episode.world * 3]! + shopOffsets[c * 3]! + Math.cos(angle) * spread,
        0.15,
        worldCenters[episode.world * 3 + 2]! + shopOffsets[c * 3 + 2]! + Math.sin(angle) * spread,
      );
    }
  }
  return {
    ringRadius: radius,
    worldCenters,
    shopOffsets,
    productSlots,
    productPositions: new Float32Array(positions),
  };
}

/** World-space xyz of one path stop, written into `out` at offset `o`. */
export function stopPoint(
  snapshot: Snapshot,
  layout: Layout,
  world: number,
  stop: Stop,
  out: Float32Array,
  o: number,
): void {
  const cx = layout.worldCenters[world * 3]!;
  const cz = layout.worldCenters[world * 3 + 2]!;
  const r = layout.ringRadius;
  const [kind, ref] = stop;
  let x = 0;
  let z = 0;
  if (kind === 0) z = r + 1.5; // spawn: the shopper pool, just outside the ring
  else if (kind === 4) [x, z] = [-1.4, r * 0.55]; // checkout gate
  else if (kind === 5) [x, z] = [1.4, r * 0.55]; // refusal gate
  else if (kind === 3 && layout.productSlots.has(`${world}:${ref}`)) {
    const slot = layout.productSlots.get(`${world}:${ref}`)!;
    out[o] = layout.productPositions[slot * 3]!;
    out[o + 1] = 0.3;
    out[o + 2] = layout.productPositions[slot * 3 + 2]!;
    return;
  } else if (kind === 2 || kind === 3) {
    const product = kind === 3 ? snapshot.products[ref] : undefined;
    const c = kind === 2 ? ref : snapshot.categories.findIndex((cat) => cat.id === product?.category);
    if (c >= 0) [x, z] = [layout.shopOffsets[c * 3]!, layout.shopOffsets[c * 3 + 2]!];
  }
  out[o] = cx + x;
  out[o + 1] = 0.3;
  out[o + 2] = cz + z;
}

export type Paths = {
  stops: Float32Array; // xyz of every stop of every rendered episode, back to back
  offsets: Uint32Array; // first stop index of rendered episode i
  counts: Uint16Array; // stop count of rendered episode i
  phase: Float32Array; // seconds of loop offset, so the crowd never moves in lockstep
};

/** Resolve every rendered stop to world space once, so the frame loop only interpolates (no strings, no hashing). */
export function buildPaths(snapshot: Snapshot, layout: Layout, rendered: readonly number[]): Paths {
  const offsets = new Uint32Array(rendered.length);
  const counts = new Uint16Array(rendered.length);
  const phase = new Float32Array(rendered.length);
  let total = 0;
  rendered.forEach((e, i) => {
    const episode = snapshot.episodes[e]!;
    offsets[i] = total;
    counts[i] = episode.path.length;
    phase[i] = ((fnv1a(episode.id) % 1000) / 1000) * episode.path.length * HOP_SECONDS;
    total += episode.path.length;
  });
  const stops = new Float32Array(total * 3);
  rendered.forEach((e, i) => {
    const episode = snapshot.episodes[e]!;
    episode.path.forEach((stop, k) =>
      stopPoint(snapshot, layout, episode.world, stop as Stop, stops, (offsets[i]! + k) * 3),
    );
  });
  return { stops, offsets, counts, phase };
}

/** Each rendered episode's position at `time` seconds: hops between its stops, phase-offset, looping. */
export function writePositions(paths: Paths, time: number, out: Float32Array): void {
  const { stops, offsets, counts, phase } = paths;
  for (let i = 0; i < counts.length; i++) {
    const hops = counts[i]! - 1;
    const duration = (hops + 1) * HOP_SECONDS; // final hop + a dwell at the last stop
    const local = (time + phase[i]!) % duration;
    const seg = Math.min(Math.floor(local / HOP_SECONDS), hops);
    const a = (offsets[i]! + seg) * 3;
    const o = i * 3;
    if (seg >= hops) {
      out[o] = stops[a]!;
      out[o + 1] = stops[a + 1]!;
      out[o + 2] = stops[a + 2]!;
      continue;
    }
    const f = local / HOP_SECONDS - seg;
    const ease = f * f * (3 - 2 * f);
    const b = a + 3;
    out[o] = stops[a]! + (stops[b]! - stops[a]!) * ease;
    out[o + 1] = stops[a + 1]! + Math.sin(f * Math.PI) * 0.35;
    out[o + 2] = stops[a + 2]! + (stops[b + 2]! - stops[a + 2]!) * ease;
  }
}
