"""Task contracts for deterministic Crucible evaluation inputs."""

from tasks.batch import (
    BatchConfig,
    BatchManifest,
    DifficultyMix,
    ReviewTrapPlan,
    TaskBatch,
    generate_batch,
)
from tasks.review_signals import (
    ExtractionResult,
    LexicalRule,
    extract_lexical_signals,
    record_human_review,
    validate_signal_text,
)
from tasks.schemas import (
    Ambiguity,
    AttributeConstraint,
    ConstraintOperator,
    Difficulty,
    HumanReviewStatus,
    HardConstraints,
    ImpliedNeed,
    ResearchRequirements,
    ReviewSignal,
    SignalVerification,
    TaskSpec,
    TaskSplit,
)

__all__ = [
    "BatchConfig",
    "BatchManifest",
    "Ambiguity",
    "AttributeConstraint",
    "ConstraintOperator",
    "Difficulty",
    "DifficultyMix",
    "ExtractionResult",
    "HumanReviewStatus",
    "LexicalRule",
    "HardConstraints",
    "ImpliedNeed",
    "ResearchRequirements",
    "ReviewSignal",
    "ReviewTrapPlan",
    "SignalVerification",
    "TaskBatch",
    "TaskSpec",
    "TaskSplit",
    "generate_batch",
    "extract_lexical_signals",
    "record_human_review",
    "validate_signal_text",
]
