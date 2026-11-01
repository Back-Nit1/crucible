import { render, screen } from "@testing-library/react";
import { getSample } from "@/lib/api/samples";
import {
  generationDetailSchema,
  generationSchema,
  killRuleSchema,
  leaderboardSchema,
  pageSchema,
} from "@/lib/api/schemas";
import { WorldDashboard } from "./world-dashboard";

describe("WorldDashboard", () => {
  it("labels scripted evidence and renders complete refusal denominators", () => {
    render(
      <WorldDashboard
        generations={pageSchema(generationSchema).parse(getSample("world_generations").body)}
        current={generationDetailSchema.parse(getSample("world_generation_detail").body)}
        leaderboard={pageSchema(leaderboardSchema).parse(getSample("world_leaderboard").body)}
        killRules={killRuleSchema.array().parse(getSample("world_kill_rules").body)}
        sample
      />,
    );

    expect(screen.getAllByText(/scripted pipeline/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/21 \/ 24 impossible runs/i)).toBeVisible();
    expect(screen.getByText(/scripted shoppers read task reference answers/i)).toBeVisible();
  });

  it("does not turn unavailable grounding metrics into zero", () => {
    render(
      <WorldDashboard
        generations={pageSchema(generationSchema).parse(getSample("world_generations").body)}
        current={generationDetailSchema.parse(getSample("world_generation_detail").body)}
        leaderboard={pageSchema(leaderboardSchema).parse(getSample("world_leaderboard").body)}
        killRules={killRuleSchema.array().parse(getSample("world_kill_rules").body)}
        sample
      />,
    );

    expect(screen.getByText("Review grounding").closest("article")).toHaveTextContent("Not measured");
  });
});
