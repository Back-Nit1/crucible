import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HomePage from "./page";

describe("HomePage", () => {
  it("labels sample data and renders the honest no-match replay", async () => {
    const user = userEvent.setup();
    render(<HomePage />);
    expect(screen.getAllByText(/sample data/i).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: /no-match replay/i }));
    expect(screen.getByRole("heading", { name: /no realistic match found/i })).toBeVisible();
    expect(screen.getByText(/verified in catalog/i)).toBeVisible();
  });
});
