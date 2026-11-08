"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import type { GenerationSnapshot } from "@/lib/api/types";
import { BUDGET } from "./motion";
import { useObservatoryStore } from "./observatory-store";

const CrowdScene = dynamic(() => import("./crowd-scene"), {
  ssr: false,
  loading: () => <p className="p-6 text-sm text-slate-400">Loading the world…</p>,
});

/** Phase A perf harness: every recorded episode of one generation, within the MacBook budget. */
export function CrowdHarness({ snapshot }: { snapshot: GenerationSnapshot }) {
  const playing = useObservatoryStore((s) => s.playing);
  const togglePlaying = useObservatoryStore((s) => s.togglePlaying);
  const [fps, setFps] = useState<number | null>(null);
  const shown = Math.min(snapshot.episodes.length, BUDGET.MAX_SHOPPERS);

  return (
    <section className="relative h-screen w-full bg-[#020a08] text-slate-100" aria-label="Observatory performance harness">
      <div className="absolute inset-0" aria-hidden="true">
        <CrowdScene snapshot={snapshot} playing={playing} onFps={setFps} />
      </div>
      <div className="absolute top-4 left-4 space-y-1 rounded-lg bg-black/60 p-4 font-mono text-xs">
        <p>generation {snapshot.generation_id}</p>
        <p data-testid="shown">
          showing {shown} of {snapshot.limits.episodes_total}
          {snapshot.limits.sampled ? " (sampled)" : ""}
          {snapshot.limits.episodes_untraced ? ` · ${snapshot.limits.episodes_untraced} skipped, not drawn` : ""}
        </p>
        <p>
          {snapshot.worlds.length} worlds · {snapshot.categories.length} categories · {snapshot.agents.length} agents
        </p>
        <p data-testid="fps">fps {playing ? (fps ?? "…") : "paused"}</p>
        <p>
          {snapshot.scripted === null
            ? "SOURCE NOT YET KNOWN"
            : snapshot.scripted
              ? "WORLD ENGINE REPLAY · NOT QWEN PERFORMANCE"
              : "QWEN MODEL ROLLOUT"}
        </p>
        <button type="button" onClick={togglePlaying} className="mt-2 rounded border border-slate-500 px-3 py-1">
          {playing ? "Pause" : "Play"}
        </button>
      </div>
    </section>
  );
}
