import { render, screen } from "@testing-library/react";
import { getSample } from "@/lib/api/samples";
import {
  generationDetailSchema,
  killLogSchema,
  killRuleSchema,
  ledgerRowSchema,
  pageSchema,
} from "@/lib/api/schemas";
import { SafetyDashboard } from "./safety-dashboard";

describe("safety and ledger views", () => {
  it("keeps Loophole Hunter candidates visibly inert and groups co-fired rules", () => {
    render(
      <SafetyDashboard
        rules={killRuleSchema.array().parse(getSample("world_kill_rules").body)}
        kills={pageSchema(killLogSchema).parse(getSample("world_kills").body)}
        generation={generationDetailSchema.parse(getSample("world_generation_detail").body)}
        sample
      />,
    );

    expect(screen.getAllByText(/proposal only. no rule is enabled/i).length).toBeGreaterThan(0);
    expect(screen.getByText("3 rules fired")).toBeVisible();
  });

  it("rejects production ledger modes and accepts only mock or sandbox", () => {
    const ledger = pageSchema(ledgerRowSchema).parse(getSample("payments_ledger").body);
    expect(ledger.items.every((row) => row.mode === "mock" || row.mode === "sandbox")).toBe(true);
    expect(() =>
      ledgerRowSchema.parse({
        mode: "production",
        episode_id: "ep",
        event: "captured",
        product_id: null,
        amount: null,
        references: [],
      }),
    ).toThrow();
  });
});
