import { render, screen } from "@testing-library/react";
import { SystemDashboard } from "./system-dashboard";

describe("SystemDashboard", () => {
  it("marks missing sample readiness as unavailable instead of healthy", () => {
    render(<SystemDashboard health={{ status: "ok" }} readiness={null} config={null} generations={null} sample refreshedAt="2026-11-01T12:00:00Z" />);
    expect(screen.getAllByText("Not exposed").length).toBeGreaterThan(0);
    expect(screen.getByText(/sanitized static api samples/i)).toBeVisible();
  });

  it("never needs secret-valued props", () => {
    const { container } = render(<SystemDashboard health={{ status: "ok" }} readiness={null} config={null} generations={null} sample refreshedAt="2026-11-01T12:00:00Z" />);
    expect(container.textContent).not.toMatch(/client_secret|api_key|buyer_password/i);
  });

  it("shows loop stages, the blocking gate variables and labels dry runs", () => {
    const loop = {
      kill_switch: false,
      iterations: [
        { iteration_id: "dry-1", next_stage: null, stages: [{ stage: "train", status: "done", evidence: "pipeline_evidence_scripted_dry_run" }] },
        { iteration_id: "it-1", next_stage: "generate", stages: [{ stage: "generate", status: "blocked", missing: ["CRUCIBLE_MODAL_APPROVED_CEILING_USD"] }] },
      ],
    };
    render(<SystemDashboard health={{ status: "ok" }} readiness={null} config={null} generations={null} loop={loop} sample refreshedAt="2026-11-01T12:00:00Z" />);
    expect(screen.getByText("generate: blocked")).toBeVisible();
    expect(screen.getByText(/generate needs CRUCIBLE_MODAL_APPROVED_CEILING_USD/)).toBeVisible();
    expect(screen.getByText(/scripted pipeline evidence/i)).toBeVisible();
    expect(screen.getByText("next: generate")).toBeVisible();
  });
});
