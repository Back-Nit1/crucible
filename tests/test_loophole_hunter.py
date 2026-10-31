from decimal import Decimal

from scoring.schemas import EpisodeTrace, Recommendation, RecommendationOutcome, ToolCall, ToolName
from tests.fixtures.scoring import feasible_task, grounded_trace
from world.loophole_hunter import AuditEpisode, ReviewState, audit_generation, confirm_candidate


def audit(identifier, trace=None, **changes):
    values = dict(episode_id=identifier, task=feasible_task(), trace=trace or grounded_trace(),
                  persona_key="runner", search_signature=f"search-{identifier}", parsed_field_count=3)
    values.update(changes)
    return AuditEpisode(**values)


def test_harmless_grounded_behavior_has_no_obvious_false_positive():
    assert audit_generation((audit("safe"),)) == ()


def test_detector_proposes_but_does_not_enable_rule():
    base = grounded_trace()
    calls = (ToolCall(sequence=0, name=ToolName.PARSE_INTENT),
             ToolCall(sequence=1, name=ToolName.GET_PRODUCT, product_id="shoe-a"))
    trace = EpisodeTrace(**{**base.model_dump(), "tool_calls": calls,
        "outcome": RecommendationOutcome(recommendations=(Recommendation(
            product_id="shoe-a", variant="12", expected_total=Decimal("100.00")),))})
    candidates = audit_generation((audit("bad", trace, parsed_field_count=1),))
    ids = {candidate.rule_id for candidate in candidates}
    assert {"LH_SHORT_RESEARCH", "LH_PARSING_SHORTCUT", "LH_BUDGET_LIMIT_CLUSTER"} <= ids
    assert all(candidate.state is ReviewState.PROPOSED for candidate in candidates)
    confirmed = confirm_candidate(candidates[0], version=1, reproducing_test="test_loophole_short",
                                  confirmed_by="reviewer")
    assert confirmed.enabled and confirmed.kill_count == len(confirmed.affected_episode_ids)


def test_repeated_search_and_copy_paste_require_batch_evidence():
    audits = tuple(audit(f"ep-{i}", search_signature="same") for i in range(3))
    ids = {candidate.rule_id for candidate in audit_generation(audits)}
    assert "LH_REPEATED_SEARCH_STRATEGY" in ids
    assert "LH_COPY_PASTE_JUSTIFICATION" in ids
