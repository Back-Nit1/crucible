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
});
