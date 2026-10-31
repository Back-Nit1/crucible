"""Small synthetic fixtures used only to exercise scoring contracts."""

from datetime import date, datetime, timezone
from decimal import Decimal

from catalog.providers.base import Product, Review
from scoring.schemas import (
    EpisodeTrace,
    Recommendation,
    RecommendationOutcome,
    ReviewClaim,
    ReviewSort,
    ToolCall,
    ToolName,
)
from tasks.schemas import Difficulty, HardConstraints, TaskSpec, TaskSplit


class InMemoryCatalog:
    """Deterministic `CatalogProvider` implementation with no external I/O."""

    def __init__(self):
        as_of = datetime(2023, 9, 1, tzinfo=timezone.utc)
        self.products = {
            "shoe-a": Product(
                id="shoe-a",
                title="Fixture Daily Trainer",
                brand="Fixture",
                category="running-shoes",
                price=Decimal("89.00"),
                variants={"12": 2, "13": 0},
                attributes={"cushioning": "high"},
                source="synthetic-test-fixture",
                as_of=as_of,
            ),
            "shoe-b": Product(
                id="shoe-b",
                title="Fixture Stable Runner",
                brand="Fixture",
                category="running-shoes",
                price=Decimal("99.00"),
                variants={"12": 1},
                attributes={"cushioning": "medium"},
                source="synthetic-test-fixture",
                as_of=as_of,
            ),
            "headphone-a": Product(
                id="headphone-a",
                title="Fixture Headphones",
                brand="Fixture",
                category="headphones",
                price=Decimal("70.00"),
                variants={"standard": 4},
                source="synthetic-test-fixture",
                as_of=as_of,
            ),
        }
        self.reviews = {
            "shoe-a": (
                Review(
                    id="review-a-positive",
                    product_id="shoe-a",
                    rating=5,
                    text="Test fixture: cushioning remained supportive.",
                    date=date(2023, 8, 1),
                    verified=True,
                ),
                Review(
                    id="review-a-critical",
                    product_id="shoe-a",
                    rating=2,
                    text="Test fixture: toe box felt narrow.",
                    date=date(2023, 8, 2),
                    verified=True,
                ),
            ),
            "shoe-b": (
                Review(
                    id="review-b-positive",
                    product_id="shoe-b",
                    rating=4,
                    text="Test fixture: stable on long runs.",
                    date=date(2023, 7, 1),
                    verified=True,
                ),
                Review(
                    id="review-b-critical",
                    product_id="shoe-b",
                    rating=3,
                    text="Test fixture: upper runs warm.",
                    date=date(2023, 7, 2),
                    verified=True,
                ),
            ),
            "headphone-a": (
                Review(
                    id="review-headphone",
                    product_id="headphone-a",
                    rating=5,
                    text="Test fixture: clear sound.",
                    date=date(2023, 6, 1),
                    verified=True,
                ),
            ),
        }

    def search(self, query: str, filters: dict | None = None) -> list[Product]:
        filters = filters or {}
        category = filters.get("category")
        return [
            product
            for product in self.products.values()
            if query.casefold() in product.title.casefold()
            and (category is None or product.category == category)
        ]

    def get_product(self, product_id: str) -> Product | None:
        return self.products.get(product_id)

    def get_reviews(
        self, product_id: str, focus: str | None = None, limit: int = 10
    ) -> list[Review]:
        return list(self.reviews.get(product_id, ()))[:limit]


def feasible_task(**changes) -> TaskSpec:
    values = {
        "id": "task-1",
        "catalog_snapshot_id": "snapshot-test-v1",
        "raw_message": "Need running shoes under $100, size 12, with cushioning.",
        "hard_constraints": HardConstraints(
            category="running-shoes",
            max_total=Decimal("100.00"),
            required_variant="12",
        ),
        "feasible_set": ("shoe-a", "shoe-b"),
        "best_value_reference": "shoe-a",
        "difficulty": Difficulty.EASY,
        "is_impossible": False,
        "split": TaskSplit.TEST,
    }
    values.update(changes)
    return TaskSpec(**values)


def grounded_trace(**changes) -> EpisodeTrace:
    values = {
        "task_id": "task-1",
        "catalog_snapshot_id": "snapshot-test-v1",
        "tool_calls": (
            ToolCall(sequence=0, name=ToolName.PARSE_INTENT),
            ToolCall(sequence=1, name=ToolName.GET_PRODUCT, product_id="shoe-a"),
            ToolCall(
                sequence=2,
                name=ToolName.COMPARE,
                product_ids=("shoe-a", "shoe-b"),
            ),
            ToolCall(
                sequence=3,
                name=ToolName.GET_REVIEWS,
                product_id="shoe-a",
                review_ids=("review-a-positive", "review-a-critical"),
                review_focus="cushioning",
                review_sort=ReviewSort.RELEVANT,
                limit=2,
            ),
        ),
        "outcome": RecommendationOutcome(
            recommendations=(
                Recommendation(
                    product_id="shoe-a",
                    variant="12",
                    expected_total=Decimal("89.00"),
                    review_claims=(
                        ReviewClaim(
                            concern="cushioning",
                            claim="Review evidence discusses cushioning support.",
                            review_ids=("review-a-positive", "review-a-critical"),
                        ),
                    ),
                ),
            ),
            assumptions=("Size 12 is exact.",),
        ),
    }
    values.update(changes)
    return EpisodeTrace(**values)
