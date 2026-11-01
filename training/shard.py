"""Parse and verify a dataset shard (stdlib only; this is what the trainer container runs). The container never trusts
what was uploaded: the shard must hash to the dataset_hash the run was approved with and bind the same training
manifest hash."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from training.dataset import DATASET_FORMAT  # noqa: F401  (format constant lives with the writer)


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


def parse_shard(data: bytes, *, expected_dataset_hash: str, expected_manifest_hash: str) -> Shard:
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_dataset_hash:
        raise ShardError("dataset_hash_mismatch", "shard bytes do not hash to the approved dataset_hash")
    try:
        lines = [json.loads(line) for line in data.decode().splitlines() if line.strip()]
        header = lines[0]["header"]
        examples = [line["messages"] for line in lines[1:]]
        ids = [line["source_episode_id"] for line in lines[1:]]
    except (ValueError, KeyError, IndexError, TypeError):
        raise ShardError("malformed_shard", "shard is not valid crucible-sft-chat-v1 JSONL") from None
    if header.get("format") != DATASET_FORMAT:
        raise ShardError("unsupported_format", "unknown dataset format")
    if header.get("training_manifest_hash") != expected_manifest_hash:
        raise ShardError("training_manifest_mismatch", "shard was built from a different training manifest")
    if header.get("record_count") != len(examples) or not examples:
        raise ShardError("record_count_mismatch", "header record_count disagrees with the shard body")
    return Shard(system=header["system"], tools=header["tools"], examples=examples, episode_ids=ids,
                 training_manifest_hash=expected_manifest_hash, dataset_hash=actual)
