"""Versioned system prompts for model-backed shoppers.

A genome's `system_prompt_variant` is a registry key, optionally followed by `| <mutation>` suffixes produced by
`DeterministicMutationProposer`. Anything unknown fails closed (fixture variants are scripted-only). Prompts contain
no task data, catalog data or reference answers; the only task input a model sees is the buyer's message."""
from __future__ import annotations

PROMPT_VERSION = "shopper-prompts-v1"

_CORE = (
    "You are a careful shopping agent acting for a buyer. Respond with exactly one tool call per turn, using only "
    "the provided tools. Never invent product IDs or review IDs: use only IDs returned by tools. The buyer's budget "
    "is an all-in cap. Order: parse_intent, search_catalog, get_product for candidates, compare, get_reviews, "
    "summarize_review_evidence (cite only review IDs you read for that product), propose_purchase, then "
    "confirm_and_pay with the pending order ID. If nothing real satisfies the constraints, call report_no_match "
    "naming the closest real product and why it misses. Unknown stock, size, tax or shipping stay unknown."
)
PROMPTS = {
    "grounded-shopper-v1": _CORE,
    "grounded-shopper-v2": _CORE + " Compare at least three candidates before choosing.",
    "grounded-shopper-v3": _CORE + " Read critical reviews first and let them change your choice when they matter.",
}
MUTATIONS = {
    "verify constraints": "Re-check every hard constraint against tool results before proposing a purchase.",
    "cite review ids": "Every review claim must cite the exact review IDs that support it.",
    "state assumptions": "State each assumption you make explicitly in the tool arguments.",
}


def system_prompt(variant: str) -> str:
    base, *suffixes = [part.strip() for part in variant.split("|")]
    if base not in PROMPTS or any(s not in MUTATIONS for s in suffixes):
        raise ValueError(f"no model prompt registered for variant {variant!r}")
    return " ".join([PROMPTS[base], *(MUTATIONS[s] for s in suffixes)])
