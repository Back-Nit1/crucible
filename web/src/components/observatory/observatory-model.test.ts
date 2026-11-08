import { getSample } from "@/lib/api/samples";
import {
  episodeDetailSchema,
  episodeSchema,
  generationDetailSchema,
  killRuleSchema,
  leaderboardSchema,
  pageSchema,
} from "@/lib/api/schemas";
import { buildObservatoryModel } from "./observatory-model";

describe("buildObservatoryModel", () => {
  it("turns the sanitized generation archive into a truthful scene model", () => {
    const generation = generationDetailSchema.parse(getSample("world_generation_detail").body);
    const episodes = pageSchema(episodeSchema).parse(getSample("world_episodes").body);
    const leaderboard = pageSchema(leaderboardSchema).parse(getSample("world_leaderboard").body);
    const episode = episodeDetailSchema.parse(getSample("world_episode_detail").body);
    const killRules = killRuleSchema.array().parse(getSample("world_kill_rules").body);

    const model = buildObservatoryModel(generation, episodes, leaderboard, episode, killRules);

    expect(model.generationId).toBe("gen-20261101-p8-t12");
    expect(model.agents).toHaveLength(8);
    expect(model.products.length).toBeGreaterThanOrEqual(10);
    expect(model.shops.map((shop) => shop.name)).toEqual([
      "Sports And Outdoors",
      "Clothing Shoes And Jewelry",
      "Office Products",
    ]);
    expect(model.mission).toMatchObject({ budget: "3.98", currency: "USD" });
    expect(model.training).toEqual({
      currentCheckpoint: "scripted-v1",
      state: "scripted_replay",
    });
    expect(model.rules).toHaveLength(8);
    expect(model.culled).toBe(model.populationSize - model.survivors);
    expect(model.episode.steps.map((step) => step.tool)).toEqual([
      "parse_intent",
      "search_catalog",
      "get_product",
      "get_product",
      "compare",
      "report_no_match",
    ]);
    expect(model.scripted).toBe(true);
    expect(model.agents.find((agent) => agent.variant === "fixture-hallucinator")).toMatchObject({
      survivor: false,
      killRules: expect.arrayContaining(["K001_HALLUCINATED_PRODUCT"]),
    });
  });
});
