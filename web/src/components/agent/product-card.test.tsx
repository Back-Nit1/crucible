import { render, screen } from "@testing-library/react";
import { ProductCard } from "./product-card";

describe("ProductCard", () => {
  it("renders API-owned unknown stock and size without inferring them", () => {
    render(
      <ProductCard
        product={{
          type: "product_card",
          seq: 2,
          at: "2026-11-01T12:00:00Z",
          product_id: "REAL-1",
          title: "Grounded product",
          brand: null,
          category: "headphones",
          price: "12.00",
          currency: "USD",
          stock: { status: "unknown", units_by_variant: {} },
          size_options: null,
          recommended: true,
          provenance: {
            source: "elastic_snapshot",
            as_of: "2023-09-30T00:00:00Z",
            snapshot: true,
            catalog_manifest_hash: "catalog-1",
            source_id: "SOURCE-1",
          },
        }}
        reviews={[]}
        unknownConstraints={["stock", "size"]}
        selected={false}
        selectable
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText(/category \/ stock \/ size/i).parentElement).toHaveTextContent(
      /unknown · size unknown/i,
    );
    expect(
      screen.getByText(/unverified or limiting: stock, size, size options/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/ratings are not used as a substitute/i)).toBeInTheDocument();
  });
});
