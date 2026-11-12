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

  it("places crowd shoppers' products in the world and keeps the generation choices", () => {
    const generation = generationDetailSchema.parse(getSample("world_generation_detail").body);
    const episodes = pageSchema(episodeSchema).parse(getSample("world_episodes").body);
    const leaderboard = pageSchema(leaderboardSchema).parse(getSample("world_leaderboard").body);
    const episode = episodeDetailSchema.parse(getSample("world_episode_detail").body);
    const crowd = [
      {
        episode_id: "e-crowd",
        agent_id: "genome-x",
        task_id: "t",
        category: "Office_Products",
        checkpoint: "qwen-3b-lora",
        killed: false,
        fitness: 0.5,
        termination: "success",
        products: ["crowd-only-product"],
        steps: [{ tool: "search_catalog", references: [], error_code: null }],
      },
    ];
    const choices = [
      {
        generation_id: "live-gen",
        status: "unpublished",
        published: false,
        episodes: 3,
        population_size: 0,
        survivors: 0,
      },
    ];
    const model = buildObservatoryModel(
      generation,
      episodes,
      leaderboard,
      episode,
      [],
      crowd,
      choices,
    );
    expect(model.crowd).toHaveLength(1);
    expect(model.choices).toEqual(choices);
    expect(model.products.find((p) => p.id === "crowd-only-product")).toMatchObject({
      category: "Office_Products",
    });
  });
});
