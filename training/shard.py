"""Parse and verify a dataset shard (stdlib only; this is what the trainer container runs). The container never trusts
what was uploaded: the shard must hash to the dataset_hash the run was approved with and bind the same training
manifest hash."""
from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass

DATASET_FORMAT = "crucible-sft-chat-v1"
GRPO_FORMAT = "crucible-grpo-v1"  # same layout + per-row system prompt and one advantage per assistant turn


class ShardError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Shard:
    system: str
    tools: list[dict]
    examples: list[list[dict]]      # chat messages per example, without the system turn
    episode_ids: list[str]
    training_manifest_hash: str
    dataset_hash: str
    source_model_version: str       # which policy produced the traces (e.g. "scripted-v1" = oracle, not a model)
    format: str = DATASET_FORMAT
    example_systems: list[str] | None = None        # GRPO: the system prompt each rollout's policy saw
    turn_advantages: list[list[float]] | None = None  # GRPO: one advantage per assistant turn, in order


def parse_shard(data: bytes, *, expected_dataset_hash: str, expected_manifest_hash: str) -> Shard:
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_dataset_hash:
        raise ShardError("dataset_hash_mismatch", "shard bytes do not hash to the approved dataset_hash")
    try:
        lines = (json.loads(line) for line in io.BytesIO(data) if line.strip())
        header = next(lines)["header"]
        examples, ids = [], []
        grpo = header.get("format") == GRPO_FORMAT
        systems = [] if grpo else None
        advantages = [] if grpo else None
        for line in lines:
            examples.append(line["messages"])
            ids.append(line["source_episode_id"])
            if grpo:
                systems.append(str(line["system"]))
                advantages.append([float(a) for a in line["turn_advantages"]])
    except (ValueError, KeyError, IndexError, TypeError, StopIteration):
        raise ShardError("malformed_shard", "shard is not valid crucible JSONL") from None
    if header.get("format") not in (DATASET_FORMAT, GRPO_FORMAT):
        raise ShardError("unsupported_format", "unknown dataset format")
    if grpo and any(sum(m.get("role") == "assistant" for m in ex) != len(adv) for ex, adv in zip(examples, advantages)):
        raise ShardError("advantage_turn_mismatch", "each assistant turn needs exactly one advantage")
    if header.get("training_manifest_hash") != expected_manifest_hash:
        raise ShardError("training_manifest_mismatch", "shard was built from a different training manifest")
    if header.get("record_count") != len(examples) or not examples:
        raise ShardError("record_count_mismatch", "header record_count disagrees with the shard body")
    return Shard(system=header["system"], tools=header["tools"], examples=examples, episode_ids=ids,
                 training_manifest_hash=expected_manifest_hash, dataset_hash=actual,
                 source_model_version=str(header.get("source_model_version", "")), format=header["format"],
                 example_systems=systems, turn_advantages=advantages)
