import { render, screen } from "@testing-library/react";
import { TrainingCard } from "./training-card";

describe("TrainingCard", () => {
  it("shows the live run's model, algorithm, progress and loss", () => {
    render(
      <TrainingCard
        run={{
          run_id: "grpo-abc123456789xyz",
          algorithm: "grpo",
          base_model: "Qwen/Qwen2.5-3B-Instruct",
          gpu: "L4",
          status: "running",
          step: 25,
          total_steps: 100,
          loss: 0.42315,
          losses: [0.9, 0.7, 0.42315],
          started_at: null,
          updated_at: new Date().toISOString(),
        }}
      />,
    );
    expect(screen.getByText("Qwen2.5-3B-Instruct")).toBeInTheDocument();
    expect(screen.getByText(/GRPO · L4/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
    expect(screen.getByText("0.4232")).toBeInTheDocument();
  });
});
