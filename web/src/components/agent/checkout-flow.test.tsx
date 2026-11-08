import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { BuyerEventOf, BuyerRun } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { CheckoutFlow, safePayPalUrl } from "./checkout-flow";

const quote: BuyerEventOf<"quote"> = {
  type: "quote",
  seq: 4,
  at: "2026-11-01T12:00:00Z",
  quote_id: "quote-1",
  product_id: "REAL-1",
  variant: "default",
  currency: "USD",
  subtotal: "89",
  shipping: "5",
  tax: "2.25",
  discounts: "0",
  total: "96.25",
  basis: "all_in",
  unknown_components: [],
  quoted_at: "2026-11-01T12:00:00Z",
  expires_at: "2026-11-01T12:10:00Z",
  fresh: true,
  budget_cap: "100",
  budget_checked_on: "all_in_total",
  within_budget: true,
};
const confirmation: BuyerEventOf<"confirmation_request"> = {
  type: "confirmation_request",
  seq: 5,
  at: "2026-11-01T12:00:00Z",
  pending_order_id: "pending-1",
  quote_id: "quote-1",
  total: "96.25",
  currency: "USD",
  basis: "all_in",
  summary: "Buy the evidence-backed headset? Nothing is charged until you confirm.",
  requires_explicit_confirmation: true,
};
const approval: BuyerEventOf<"paypal_approval"> = {
  type: "paypal_approval",
  seq: 6,
  at: "2026-11-01T12:00:00Z",
  mode: "sandbox",
  status: "APPROVED",
  approval_url: "https://www.sandbox.paypal.com/checkoutnow?token=ORD1",
};
const receipt: BuyerEventOf<"receipt"> = {
  type: "receipt",
  seq: 7,
  at: "2026-11-01T12:01:00Z",
  mode: "sandbox",
  order_id: "SANDBOX-ORDER-1",
  capture_id: "SANDBOX-CAPTURE-1",
  amount: "96.25",
  currency: "USD",
  status: "COMPLETED",
};
const completed: BuyerRun = {
  run_id: "run-1",
  status: "completed",
  events: [quote, confirmation, approval, receipt],
  next_seq: 8,
  model: "qwen@test",
  tokens: 12,
  latency_ms: 50,
  cost_usd: null,
  cost_known: false,
};
const baseProps = {
  runId: "run-1",
  selectedProductId: "REAL-1",
  quote,
  confirmation,
  approval,
  sampleMode: false,
  onRunUpdate: vi.fn(),
};

describe("CheckoutFlow", () => {
  it("fails closed when the API did not return a verified quote", () => {
    render(
      <CheckoutFlow
        {...baseProps}
        quote={undefined}
        confirmation={undefined}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByText(/verified quote unavailable/i)).toBeVisible();
    expect(screen.getByRole("button", { name: /no checkout quote/i })).toBeDisabled();
  });

  it("requires deliberate confirmation before sandbox capture", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn().mockResolvedValue(completed);
    const onRunUpdate = vi.fn();
    render(<CheckoutFlow {...baseProps} onConfirm={onConfirm} onRunUpdate={onRunUpdate} />);

    await user.click(screen.getByRole("button", { name: /review verified quote/i }));
    const capture = await screen.findByRole("button", { name: /confirm sandbox purchase/i });
    expect(capture).toBeDisabled();
    expect(screen.getByText("$96.25")).toBeVisible();
    await user.click(screen.getByRole("checkbox", { name: /explicitly authorize/i }));
    await user.click(capture);

    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith("run-1", "pending-1"));
    expect(onRunUpdate).toHaveBeenCalledWith(completed);
  });

  it("disables capture for an expired quote", () => {
    render(<CheckoutFlow {...baseProps} quote={{ ...quote, fresh: false }} onConfirm={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/quote is expired/i);
    expect(screen.getByRole("button", { name: /review verified quote/i })).toBeDisabled();
  });

  it("reports sandbox capture failure without showing a receipt", async () => {
    const user = userEvent.setup();
    render(
      <CheckoutFlow
        {...baseProps}
        onConfirm={vi
          .fn()
          .mockRejectedValue(new ApiError("payment_failed", "INSTRUMENT_DECLINED", 402))}
      />,
    );
    await user.click(screen.getByRole("button", { name: /review verified quote/i }));
    await user.click(await screen.findByRole("checkbox", { name: /explicitly authorize/i }));
    await user.click(screen.getByRole("button", { name: /confirm sandbox purchase/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/payment backend rejected capture/i);
    expect(screen.queryByText(/capture completed/i)).not.toBeInTheDocument();
  });
});

describe("safePayPalUrl", () => {
  it("links only https PayPal pages", () => {
    expect(safePayPalUrl("https://www.sandbox.paypal.com/checkoutnow?token=1")).toContain(
      "sandbox.paypal.com",
    );
    for (const bad of [
      "javascript:alert(1)",
      "http://www.paypal.com/x",
      "https://paypal.com.evil.example/x",
      "https://evilpaypal.com/x",
      "https://mock.invalid/approve/1",
      "",
      null,
    ]) {
      expect(safePayPalUrl(bad)).toBeNull();
    }
  });
});
