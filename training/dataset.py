"""Curated SFT records + their TrainingManifest -> one deterministic, content-addressed training shard.

Runs where the repo is installed (laptop / CI), never inside the trainer container: the container receives only the
shard bytes and re-verifies their hash. Every refusal here is fail-closed and names a stable code:

  * the manifest's content hash must equal the hash recomputed from the records (no swapped or edited data);
  * record ids, order, count and deduplication hash must match the manifest;
  * every record must come from an allowed split (never test / held-out-category) and agree with the manifest's own
    `source_task_splits`, so a lying manifest cannot launder an evaluation episode;
  * no shopper PII pattern may appear anywhere in the serialized shard.

Training targets are the assistant TOOL CALLS only. `final_answer` is synthesized by the episode runner, never asked of
the model at inference, so it is deliberately not part of the shard."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from agents.model import Message, action_tools
from agents.prompts import PROMPT_VERSION, system_prompt
from agents.qwen_client import qwen_tools, to_qwen_messages
from tasks.schemas import TaskSplit
from training.curation import SFTRecord, TrainingManifest
from training.shard import DATASET_FORMAT

ALLOWED_SPLITS = frozenset({TaskSplit.TRAIN, TaskSplit.VALIDATION})
DEFAULT_PROMPT_VARIANT = "grounded-shopper-v1"
_PII = (
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),                         # email
    re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s.-])?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"),  # phone
    re.compile(r"(?<!\d)\d{13,19}(?!\d)"),                           # card-number-like digit run
)


class DatasetError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class TrainingDataset:
    shard: bytes                 # the exact bytes that are hashed, uploaded and trained on
    dataset_hash: str
    record_count: int
    training_manifest_hash: str


def curation_content_hash(records: tuple[SFTRecord, ...]) -> str:
    """Exactly the digest training.curation.curate_survivors stores in TrainingManifest.content_hash."""
    content = [record.model_dump(mode="json") for record in records]
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_records(records: tuple[SFTRecord, ...], manifest: TrainingManifest) -> None:
    if not records:
        raise DatasetError("empty_dataset", "no curated records to train on")
    ids = tuple(r.source_episode_id for r in records)
    if len(set(ids)) != len(ids):
        raise DatasetError("duplicate_episode", "a source episode appears twice")
    if ids != manifest.source_episode_ids:
        raise DatasetError("record_set_mismatch", "records do not match the manifest's source episodes")
    for record in records:
        if record.split not in ALLOWED_SPLITS or manifest.source_task_splits.get(record.source_episode_id) != record.split:
            raise DatasetError("forbidden_split", f"episode {record.source_episode_id} is not from an allowed training split")
    if any(split not in ALLOWED_SPLITS for split in manifest.splits):
        raise DatasetError("forbidden_split", "manifest lists a protected split")
    if curation_content_hash(records) != manifest.content_hash:
        raise DatasetError("manifest_hash_mismatch", "records do not hash to the manifest content_hash")
    dedup = hashlib.sha256("|".join(sorted(r.normalized_hash for r in records)).encode()).hexdigest()
    if dedup != manifest.deduplication_hash:
        raise DatasetError("dedup_hash_mismatch", "deduplication hash does not match the records")


def render_example(record: SFTRecord) -> list[dict[str, object]]:
    """SFTRecord -> runtime Message history -> Qwen chat messages (the same converter inference uses)."""
    messages: list[Message] = []
    for turn in record.messages:
        if "tool_call" in turn:
            call = dict(turn["tool_call"])  # type: ignore[arg-type]
            name = str(call.pop("type"))
            result = dict(turn["tool_result"])  # type: ignore[arg-type]
            messages.append(Message(role="assistant", tool_name=name, tool_arguments=call))
            messages.append(Message(role="tool", tool_name=name, tool_result={**result, "error_code": None}))
        elif turn["role"] == "user":
            messages.append(Message(role="user", content=str(turn["content"])))
        # the trailing synthesized final_answer turn is intentionally dropped (see module docstring)
    if not any(m.tool_name for m in messages):
        raise DatasetError("no_tool_calls", f"{record.source_episode_id} has no tool calls to learn from")
    return to_qwen_messages(messages)


def _assert_no_pii(text: str) -> None:
    for pattern in _PII:
        if pattern.search(text):
            raise DatasetError("pii_detected", "a PII-shaped value is present in the training data")


def build_dataset(records: tuple[SFTRecord, ...], manifest: TrainingManifest, *,
                  prompt_variant: str = DEFAULT_PROMPT_VARIANT) -> TrainingDataset:
    validate_records(records, manifest)
    system = system_prompt(prompt_variant)
    header = {"header": {"format": DATASET_FORMAT, "training_manifest_hash": manifest.content_hash,
                         "record_count": len(records), "source_model_version": manifest.model_version, "prompt_version": PROMPT_VERSION, "prompt_variant": prompt_variant,
                         "system": system, "tools": qwen_tools(action_tools())}}
    lines = [header] + [{"source_episode_id": r.source_episode_id, "messages": render_example(r)} for r in records]
    shard = ("\n".join(json.dumps(line, sort_keys=True, separators=(",", ":")) for line in lines) + "\n").encode()
    _assert_no_pii(json.dumps([line for line in lines[1:]]))
    return TrainingDataset(shard=shard, dataset_hash=hashlib.sha256(shard).hexdigest(), record_count=len(records),
                           training_manifest_hash=manifest.content_hash)
