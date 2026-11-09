import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { LiveResults } from "./live-results";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

describe("LiveResults", () => {
  it("shows measured probe rates with denominators and evaluation progress", () => {
    render(
      <LiveResults
        live={{
          probes: [
            {
              id: "a",
              status: "passed",
              finished_at: null,
              checkpoint: "qwen-base",
              model: "Qwen/x",
              rates: { valid_structured_call: { value: 1, numerator: 20, denominator: 20 } },
              failed_thresholds: [],
              cost_usd: "0.03",
              latency_p50_ms: 5108,
            },
            {
              id: "b",
              status: "blocked_not_run",
              finished_at: null,
              checkpoint: "qwen-base",
              model: "Qwen/x",
              rates: {},
              failed_thresholds: [],
              cost_usd: null,
              latency_p50_ms: null,
            },
          ],
          evaluations: [
            {
              evaluation_id: "eval-1",
              status: "running",
              contenders: [
                {
                  contender: "base",
                  kind: "base",
                  done: 3,
                  expected: 4,
                  killed: 1,
                  cost_usd: "0.03",
                },
              ],
            },
          ],
        }}
      />,
    );
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByText("20 / 20")).toBeInTheDocument();
    expect(screen.getByText("Not run: no numbers recorded.")).toBeInTheDocument();
    expect(screen.getByText(/3 \/ 4 episodes · 1 killed/)).toBeInTheDocument();
  });
});
