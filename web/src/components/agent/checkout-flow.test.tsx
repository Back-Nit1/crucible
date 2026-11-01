import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ProductPick } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { CheckoutFlow } from "./checkout-flow";

const pick: ProductPick = {
  product_id: "REAL-1",
  title: "Evidence-backed headset",
  price: "89.00",
  currency: "USD",
  source: "elastic_snapshot",
  as_of: "2023-09-30T00:00:00Z",
  snapshot: true,
  reason: "Matches the checkable price constraint.",
  review_evidence: [],
};

describe("CheckoutFlow", () => {
  it("fails closed when purchase context is missing", () => {
    render(
      <CheckoutFlow pick={pick} purchaseContext={null} onPropose={vi.fn()} onConfirm={vi.fn()} />,
    );

    expect(screen.getByText(/checkout context unavailable/i)).toBeVisible();
    expect(screen.getByRole("button", { name: /verify all-in quote/i })).toBeDisabled();
  });

  it("requires deliberate confirmation before sandbox capture", async () => {
    const user = userEvent.setup();
    const onPropose = vi.fn().mockResolvedValue({
      pending_order_id: "pending-1",
      product_id: "REAL-1",
      total: "96.25",
      currency: "USD",
      status: "CREATED",
      approval_url: null,
      quote_id: "quote-1",
      quote_basis: "all_in",
    });
    const onConfirm = vi.fn().mockResolvedValue({
      order_id: "SANDBOX-ORDER-1",
      capture_id: "SANDBOX-CAPTURE-1",
      amount: "96.25",
      currency: "USD",
      status: "COMPLETED",
    });
    render(
      <CheckoutFlow
        pick={pick}
        purchaseContext={{ taskId: "task-1", agentId: "agent-1", budgetCap: "100", variant: "" }}
        onPropose={onPropose}
        onConfirm={onConfirm}
      />,
    );

    await user.click(screen.getByRole("button", { name: /verify all-in quote/i }));
    const capture = await screen.findByRole("button", { name: /confirm sandbox purchase/i });
    expect(capture).toBeDisabled();
    expect(screen.getByText(/96.25 USD/i)).toBeVisible();

    await user.click(screen.getByRole("checkbox", { name: /explicitly authorize/i }));
    await user.click(capture);

    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith("pending-1"));
    expect(await screen.findByText(/sandbox capture completed/i)).toBeVisible();
    expect(screen.getByText("SANDBOX-CAPTURE-1")).toBeVisible();
  });

  it("turns an expired quote into an actionable retry state", async () => {
    const user = userEvent.setup();
    render(
      <CheckoutFlow
        pick={pick}
        purchaseContext={{ taskId: "task-1", agentId: "agent-1", budgetCap: "100", variant: "" }}
        onPropose={vi.fn().mockRejectedValue(new ApiError("quote_stale", "stale", 409))}
        onConfirm={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: /verify all-in quote/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/quote expired.*fresh quote/i);
  });

  it("reports sandbox capture failure without showing a receipt", async () => {
    const user = userEvent.setup();
    render(
      <CheckoutFlow
        pick={pick}
        purchaseContext={{ taskId: "task-1", agentId: "agent-1", budgetCap: "100", variant: "" }}
        onPropose={vi.fn().mockResolvedValue({
          pending_order_id: "pending-1",
          product_id: "REAL-1",
          total: "96.25",
          currency: "USD",
          status: "APPROVED",
          approval_url: null,
          quote_id: "quote-1",
          quote_basis: "all_in",
        })}
        onConfirm={vi.fn().mockRejectedValue(new ApiError("payment_failed", "INSTRUMENT_DECLINED", 402))}
      />,
    );
    await user.click(screen.getByRole("button", { name: /verify all-in quote/i }));
    await user.click(await screen.findByRole("checkbox", { name: /explicitly authorize/i }));
    await user.click(screen.getByRole("button", { name: /confirm sandbox purchase/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/sandbox capture failed/i);
    expect(screen.queryByText(/capture completed/i)).not.toBeInTheDocument();
  });
});
