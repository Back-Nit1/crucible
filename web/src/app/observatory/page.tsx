import { ObservatoryClient } from "@/components/observatory/observatory-client";
import { buildObservatoryModel } from "@/components/observatory/observatory-model";
import { ErrorState } from "@/components/ui/data-state";
import { serverApi } from "@/lib/api/server";
import { publicEnv } from "@/lib/env";
import type { ObservatoryModel } from "@/components/observatory/observatory-model";

export const dynamic = "force-dynamic";

export default async function ObservatoryPage() {
  const api = serverApi();
  let model: ObservatoryModel | null = null;
  let message = "The recorded world could not be mapped into the Observatory.";

  try {
    const generations = await api.generations();
    const generationId = generations.items[0]?.generation_id;
    if (!generationId) throw new Error("No generation archive is available to replay.");

    const [generation, episodes, leaderboard, killRules] = await Promise.all([
      api.generation(generationId),
      api.episodes({ generation_id: generationId, limit: 200 }),
      api.leaderboard(generationId),
      api.killRules(),
    ]);
    // Show a full story (search, reviews, purchase) when the archive has one.
    const showcase =
      episodes.items
        .filter((item) => item.termination === "success" && !item.killed)
        .sort((a, b) => b.tool_call_count - a.tool_call_count)[0] ?? episodes.items[0];
    const episodeId = showcase?.episode_id;
    if (!episodeId) throw new Error("This generation has no recorded episodes.");
    const episode = await api.episode(episodeId);
    model = buildObservatoryModel(generation, episodes, leaderboard, episode, killRules);
  } catch (error) {
    message = error instanceof Error ? error.message : message;
  }

  return model ? (
    <ObservatoryClient model={model} sample={publicEnv.NEXT_PUBLIC_DATA_MODE === "sample"} />
  ) : (
    <ErrorState title="Observatory unavailable" message={message} />
  );
}
