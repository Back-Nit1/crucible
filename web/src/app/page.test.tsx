import { render, screen } from "@testing-library/react";
import HomePage from "./page";

describe("HomePage", () => {
  it("names the evidence-first product promise", () => {
    render(<HomePage />);
    expect(screen.getByRole("heading", { name: /trust is earned in the trace/i })).toBeVisible();
    expect(screen.getByText(/keeps recommendation separate from purchase/i)).toBeVisible();
  });
});
