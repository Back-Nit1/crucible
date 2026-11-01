import { render, screen } from "@testing-library/react";
import HomePage from "./page";

describe("HomePage", () => {
  it("labels sample data and renders the honest no-match replay", () => {
    render(<HomePage />);
    expect(screen.getAllByText(/sample data/i).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: /no realistic match found/i })).toBeVisible();
    expect(screen.getByText(/no purchase proposed/i)).toBeVisible();
  });
});
