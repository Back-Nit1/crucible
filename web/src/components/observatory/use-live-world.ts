"use client";

import { useEffect, useState } from "react";
import { crowdEpisodeSchema, learningRoundSchema, trainingRunSchema } from "@/lib/api/schemas";
import type { CrowdEpisode, LearningRound, TrainingRun } from "@/lib/api/types";

export type LiveState = {
  connection: "off" | "connecting" | "open" | "retrying";
  crowd: CrowdEpisode[];
  training: TrainingRun[];
  rounds: LearningRound[];
  episodes: number | null;
  arrived: number; // new episodes seen since the page loaded
  lastEpisodeAt: number | null;
};

/** Server-sent events from GET /observatory/{id}/live: new episodes join the crowd (oldest leave once it is full),
 * training progress replaces the previous snapshot. EventSource reconnects on its own after errors. */
export function useLiveWorld(
  apiBaseUrl: string,
  generationId: string,
  initialCrowd: CrowdEpisode[],
  initialRounds: LearningRound[],
  enabled: boolean,
  maxCrowd = 30,
): LiveState {
  const [state, setState] = useState<LiveState>({
    connection: enabled ? "connecting" : "off",
    crowd: initialCrowd,
    training: [],
    rounds: initialRounds,
    episodes: null,
    arrived: 0,
    lastEpisodeAt: null,
  });

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    const source = new EventSource(
      new URL(`/observatory/${encodeURIComponent(generationId)}/live`, apiBaseUrl),
    );
    const read = (event: Event) => {
      try {
        return JSON.parse((event as MessageEvent<string>).data) as unknown;
      } catch {
        return null;
      }
    };
    source.onopen = () => setState((s) => ({ ...s, connection: "open" }));
    source.onerror = () => setState((s) => ({ ...s, connection: "retrying" }));
    source.addEventListener("status", (event) => {
      const data = read(event) as { episodes?: number } | null;
      if (typeof data?.episodes === "number") setState((s) => ({ ...s, episodes: data.episodes! }));
    });
    source.addEventListener("training", (event) => {
      const runs = trainingRunSchema
        .array()
        .safeParse((read(event) as { runs?: unknown } | null)?.runs);
      if (runs.success) setState((s) => ({ ...s, training: runs.data }));
    });
    source.addEventListener("rounds", (event) => {
      const rounds = learningRoundSchema
        .array()
        .safeParse((read(event) as { rounds?: unknown } | null)?.rounds);
      if (rounds.success) setState((s) => ({ ...s, rounds: rounds.data }));
    });
    source.addEventListener("episode", (event) => {
      const episode = crowdEpisodeSchema.safeParse(read(event));
      if (!episode.success) return;
      setState((s) => ({
        ...s,
        crowd: [
          ...s.crowd.filter((item) => item.episode_id !== episode.data.episode_id),
          episode.data,
        ].slice(-maxCrowd),
        arrived: s.arrived + 1,
        lastEpisodeAt: Date.now(),
      }));
    });
    return () => source.close();
  }, [apiBaseUrl, enabled, generationId, maxCrowd]);

  return state;
}
