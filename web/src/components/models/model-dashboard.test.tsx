import { render, screen } from "@testing-library/react";
import type { ApiDocument, Page } from "@/lib/api/types";
import { ModelDashboard } from "./model-dashboard";

const emptyCheckpoints: Page<ApiDocument> = { items: [], total: 0, offset: 0, limit: 50 };

describe("ModelDashboard", () => {
  it("distinguishes a measured zero from an unavailable metric", () => {
    const evaluations: Page<ApiDocument> = {
      items: [{
        id: "base",
        data: {
          contender: "Base Qwen",
          status: "completed",
          task_set_hash: "a".repeat(64),
          seeds: [1, 2],
          metrics: {
            hallucination_rate: { value: 0, numerator: 0, denominator: 12, excluded: 0 },
          },
        },
      }],
      total: 1,
      offset: 0,
      limit: 50,
    };
    render(<ModelDashboard evaluations={evaluations} checkpoints={emptyCheckpoints} sample />);

    expect(screen.getByText("Hallucination").closest("article")).toHaveTextContent("0.0%");
    expect(screen.getByText("Success").closest("article")).toHaveTextContent("Not measured");
  });

  it("calls an empty evaluation registry not run instead of zero", () => {
    render(<ModelDashboard evaluations={{ items: [], total: 0, offset: 0, limit: 50 }} checkpoints={emptyCheckpoints} sample />);
    expect(screen.getByText(/evaluations not run/i)).toBeVisible();
    expect(screen.getByText(/no denominators exist/i)).toBeVisible();
  });
});
