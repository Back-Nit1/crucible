"""Deterministic gaming-pattern proposals with an explicit human confirmation gate."""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from scoring.schemas import EpisodeTrace, NoMatchOutcome, RecommendationOutcome, ToolName
from tasks.schemas import TaskSpec


class HunterModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewState(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class AuditEpisode(HunterModel):
    episode_id: str
    task: TaskSpec
    trace: EpisodeTrace
    persona_key: str = "general"
    search_signature: str = ""
    parsed_field_count: int = Field(default=1, ge=0)
    judge_attribute_disagreement: bool = False


class RuleCandidate(HunterModel):
    rule_id: str
    description: str
    state: ReviewState = ReviewState.PROPOSED
    evidence: tuple[str, ...]
    affected_episode_ids: tuple[str, ...]
    proposed_at: dt.date = dt.date(2026, 10, 31)


class ConfirmedLoopholeRule(HunterModel):
    rule_id: str
    version: int = Field(ge=1)
    description: str
    state: ReviewState = ReviewState.CONFIRMED
    evidence: tuple[str, ...]
    reproducing_test: str = Field(min_length=1)
    affected_episode_ids: tuple[str, ...]
    kill_count: int = Field(ge=0)
    confirmed_by: str = Field(min_length=1)
    confirmed_at: dt.date = dt.date(2026, 10, 31)
    enabled: bool = True


def _justification(audit: AuditEpisode) -> str:
    if isinstance(audit.trace.outcome, NoMatchOutcome):
        return " ".join((audit.trace.outcome.reason, audit.trace.outcome.why_it_misses)).casefold()
    return " ".join(claim.claim for item in audit.trace.outcome.recommendations
                    for claim in item.review_claims).casefold()


def audit_generation(audits: tuple[AuditEpisode, ...]) -> tuple[RuleCandidate, ...]:
    """Propose patterns only; this function never enables a kill rule."""
    findings: dict[str, list[tuple[str, str]]] = defaultdict(list)
    justifications: dict[str, list[str]] = defaultdict(list)
    searches: dict[str, list[str]] = defaultdict(list)
    review_personas: dict[frozenset[str], set[str]] = defaultdict(set)
    refusals = 0

    for audit in audits:
        trace, task = audit.trace, audit.task
        eid = audit.episode_id
        research_calls = [call for call in trace.tool_calls if call.name in {
            ToolName.SEARCH_CATALOG, ToolName.GET_PRODUCT, ToolName.COMPARE, ToolName.GET_REVIEWS}]
        if len(research_calls) < 3:
            findings["SHORT_RESEARCH"].append((eid, f"only {len(research_calls)} research calls"))
        if audit.parsed_field_count < 2:
            findings["PARSING_SHORTCUT"].append((eid, "fewer than two intent fields parsed"))
        if audit.judge_attribute_disagreement:
            findings["JUDGE_ATTRIBUTE_DISAGREEMENT"].append((eid, "judge score conflicts with catalog attributes"))
        if isinstance(trace.outcome, NoMatchOutcome):
            refusals += 1
        else:
            for item in trace.outcome.recommendations:
                ratio = item.expected_total / task.hard_constraints.max_total
                if Decimal("0.99") <= ratio <= Decimal("1"):
                    findings["BUDGET_LIMIT_CLUSTER"].append((eid, f"pick uses {ratio:.3f} of budget"))
                for claim in item.review_claims:
                    normalized = " ".join(claim.claim.casefold().split()).rstrip(".")
                    if normalized in {"reviewers love it", "great reviews", "reviews are positive"}:
                        findings["GENERIC_REVIEW_CLAIM"].append((eid, normalized))
                    review_personas[frozenset(claim.review_ids)].add(audit.persona_key)
        review_calls = [call for call in trace.tool_calls if call.name is ToolName.GET_REVIEWS]
        if any(call.limit == 1 for call in review_calls):
            findings["REVIEW_LIMIT_ONE"].append((eid, "review query limit=1"))
        for call in review_calls:
            if call.review_sort and call.review_sort.value == "relevant" and len(call.review_ids) == 1:
                findings["POSITIVE_ONLY_REVIEWS"].append((eid, "single convenient relevant review sampled"))
        justification = _justification(audit)
        if justification:
            justifications[justification].append(eid)
        if audit.search_signature:
            searches[audit.search_signature].append(eid)

    for text, episode_ids in justifications.items():
        if len(episode_ids) >= 2:
            findings["COPY_PASTE_JUSTIFICATION"].extend((eid, f"identical justification: {text[:80]}") for eid in episode_ids)
    for signature, episode_ids in searches.items():
        if len(episode_ids) >= 3:
            findings["REPEATED_SEARCH_STRATEGY"].extend((eid, f"search signature {signature}") for eid in episode_ids)
    for review_ids, personas in review_personas.items():
        if review_ids and len(personas) >= 2:
            findings["REUSED_REVIEW_ACROSS_PERSONAS"].append((
                ",".join(sorted(review_ids)), f"same evidence reused for personas {sorted(personas)}"))
    if audits and Decimal(refusals) / Decimal(len(audits)) > Decimal("0.75"):
        findings["EXCESSIVE_REFUSAL"].extend((audit.episode_id, "generation refusal rate exceeds 75%") for audit in audits)

    candidates = []
    for pattern, evidence in sorted(findings.items()):
        episode_ids = tuple(sorted({episode_id for episode_id, _ in evidence if any(
            audit.episode_id == episode_id for audit in audits)}))
        candidates.append(RuleCandidate(
            rule_id=f"LH_{pattern}", description=pattern.replace("_", " ").title(),
            evidence=tuple(sorted({detail for _, detail in evidence})),
            affected_episode_ids=episode_ids,
        ))
    return tuple(candidates)


def confirm_candidate(candidate: RuleCandidate, *, version: int, reproducing_test: str,
                      confirmed_by: str) -> ConfirmedLoopholeRule:
    if candidate.state is not ReviewState.PROPOSED:
        raise ValueError("only proposed candidates can be confirmed")
    return ConfirmedLoopholeRule(
        rule_id=candidate.rule_id, version=version, description=candidate.description,
        evidence=candidate.evidence, reproducing_test=reproducing_test,
        affected_episode_ids=candidate.affected_episode_ids,
        kill_count=len(candidate.affected_episode_ids), confirmed_by=confirmed_by,
    )
