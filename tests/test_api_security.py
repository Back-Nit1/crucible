"""Security fixes on the public API: unguessable order ids, rate limits on money/model POSTs, header hygiene,
bounded pending orders, and a response cache that never replays a foreign or corrupt entry."""
from decimal import Decimal

from api.main import RateLimit
from payments import guards
from tests.test_api_endpoints import PROPOSE, Snap, client


def test_same_body_from_two_callers_never_shares_an_order():
    c = client()
    a, b = (c.post("/purchase/propose", json=PROPOSE).json() for _ in range(2))
    assert a["pending_order_id"] != b["pending_order_id"]  # was sha256(task|agent|product|variant): guessable


def test_request_id_replays_the_same_order_and_is_validated():
    c = client()
    rid = {"request_id": "judge-retry-0123456789"}
    a, b = (c.post("/purchase/propose", json=PROPOSE | rid).json() for _ in range(2))
    assert a["pending_order_id"] == b["pending_order_id"]
    assert c.post("/purchase/propose", json=PROPOSE | {"request_id": "short"}).status_code == 422
    assert c.post("/purchase/propose", json=PROPOSE | {"task_id": "x" * 129}).status_code == 422


def test_money_posts_are_rate_limited_per_client(monkeypatch):
    monkeypatch.setenv("CRUCIBLE_RATE_LIMIT_PER_MINUTE", "2")
    c = client()
    codes = [c.post("/purchase/propose", json=PROPOSE, headers={"x-forwarded-for": "1.2.3.4"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    other = c.post("/purchase/propose", json=PROPOSE, headers={"x-forwarded-for": "5.6.7.8"})
    assert other.status_code == 200  # another client keeps its own window
    assert c.get("/health").status_code == 200  # reads are never limited


def test_total_window_is_a_backstop_against_forged_client_keys():
    t = [0.0]
    lim = RateLimit(per_client=5, total=3, clock=lambda: t[0])
    assert [lim.allow(f"forged-{i}") for i in range(4)] == [True, True, True, False]
    t[0] = 61
    assert lim.allow("forged-9")  # the window slides


def test_request_id_header_is_not_echoed_unless_safe():
    c = client()
    assert c.get("/health", headers={"x-request-id": "abc-123"}).headers["x-request-id"] == "abc-123"
    echoed = c.get("/health", headers={"x-request-id": "<script>" + "a" * 100}).headers["x-request-id"]
    assert echoed != "<script>" + "a" * 100 and len(echoed) == 16


def test_pending_orders_are_bounded(monkeypatch):
    from payments.mock import MockPayments
    monkeypatch.setattr(guards, "MAX_PENDING", 3)
    g = guards.GuardedPayments(MockPayments(auto_approve=False), Snap())
    ids = [g.propose_purchase(f"t{i}", "a", "p1", "", Decimal("80.00"), Decimal("100.00")).id for i in range(5)]
    assert len(g._pending) == 3 and ids[0] not in g._pending and ids[-1] in g._pending


def test_corrupt_or_foreign_cache_entries_are_misses(tmp_path):
    from agents.model import QwenModelAdapter
    from agents.qwen_client import ModalQwenClient
    from tests.test_agent_qwen_client import request, result
    calls = []

    def transport(payload, timeout):
        calls.append(payload)
        return result()

    QwenModelAdapter(ModalQwenClient(transport, cost_ceiling=Decimal(1), timeout_seconds=1, cache_dir=tmp_path)).generate(request())
    (entry,) = tmp_path.glob("*.json")
    for bad in ("{not json", entry.read_text().replace('"revision":"', '"revision":"x')):
        entry.write_text(bad)
        again = ModalQwenClient(transport, cost_ceiling=Decimal(1), timeout_seconds=1, cache_dir=tmp_path)
        QwenModelAdapter(again).generate(request())
        assert again.cache_hits == 0
    assert len(calls) == 3
