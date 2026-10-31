"""Deterministic scoring contracts, hard gate, and initial kill rules."""

from scoring.gate import evaluate_gate
from scoring.kill_rules import evaluate_kill_rules

__all__ = ["evaluate_gate", "evaluate_kill_rules"]
