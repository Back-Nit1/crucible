"""Integration contract: stock is enforced only where the source provides inventory (never synthesised)."""
from scoring.gate import evaluate_gate
from scoring.schemas import GateViolationCode
from tests.fixtures.scoring import InMemoryCatalog, feasible_task, grounded_trace


class NoInventoryCatalog(InMemoryCatalog):
    """Same products, but the source has no inventory data (variants == {}), like Amazon Reviews 2023."""

    def get_product(self, product_id):
        p = super().get_product(product_id)
        return p.model_copy(update={"variants": {}}) if p else p


def test_unverifiable_stock_does_not_zero_the_gate():
    result = evaluate_gate(feasible_task(), grounded_trace(), NoInventoryCatalog())
    assert result.value == 1 and result.violations == ()


class ZeroStockCatalog(InMemoryCatalog):
    def get_product(self, product_id):
        p = super().get_product(product_id)
        return p.model_copy(update={"variants": {"12": 0}}) if p else p


def test_known_zero_stock_still_fails_the_gate():
    result = evaluate_gate(feasible_task(), grounded_trace(), ZeroStockCatalog())
    assert result.value == 0 and GateViolationCode.OUT_OF_STOCK in {v.code for v in result.violations}
