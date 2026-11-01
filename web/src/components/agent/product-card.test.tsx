import { render, screen } from "@testing-library/react";
import { ProductCard } from "./product-card";

describe("ProductCard", () => {
  it("renders unknown stock size and category rather than inferring them", () => {
    render(
      <ProductCard
        pick={{
          product_id: "REAL-1",
          title: "Grounded product",
          price: "12.00",
          currency: "USD",
          source: "elastic_snapshot",
          as_of: "2023-09-30T00:00:00Z",
          snapshot: true,
          reason: "Matches the checkable category and price constraints.",
          review_evidence: [],
        }}
        selected={false}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText(/category \/ stock \/ size/i).parentElement).toHaveTextContent(
      /not provided — unknown/i,
    );
    expect(screen.getByText(/ratings are not used as a substitute/i)).toBeInTheDocument();
  });
});
