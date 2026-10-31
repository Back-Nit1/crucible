"""Leakage-safe conversion of grounded survivor episodes to versioned SFT records."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from agents.actions import EpisodeRecord, SummarizeReviewEvidence
from agents.grounding import complete_review_ids
from catalog.providers.base import CatalogProvider
from tasks.schemas import TaskSpec, TaskSplit


class TrainingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SFTRecord(TrainingModel):
    format_version: str = "crucible-tool-sft-v1"
    source_episode_id: str
    task_id: str
    split: TaskSplit
    messages: tuple[dict[str, object], ...]
    normalized_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class TrainingManifest(TrainingModel):
    manifest_version: str = "1.1"
    catalog_hash: str
    task_version: str
    rule_version: str
    model_version: str
    source_episode_ids: tuple[str, ...]
    splits: tuple[TaskSplit, ...]
    source_task_splits: dict[str, TaskSplit]
    deduplication_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: dt.datetime
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class CurationResult:
    records: tuple[SFTRecord, ...]
    manifest: TrainingManifest
    exclusions: dict[str, str]


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _grounded(episode: EpisodeRecord) -> bool:
    if episode.score_components.get("gate") not in (1, "1"):
        return False
    metrics = episode.score_components.get("quality_metrics", [])
    grounding = [metric for metric in metrics if metric.get("name") in {
        "review_grounding", "review_id_existence"}]
    return bool(grounding) and all(metric.get("value") in (1, "1", "1.0") for metric in grounding)


def _reviews_valid(episode: EpisodeRecord, catalog: CatalogProvider) -> bool:
    for call in episode.tool_calls:
        if not isinstance(call.action, SummarizeReviewEvidence):
            continue
        valid = complete_review_ids(catalog, call.action.product_id)
        cited = {review_id for claim in call.action.claims for review_id in claim.review_ids}
        if not cited or not cited <= valid:
            return False
    return True


def _record(episode: EpisodeRecord, task: TaskSpec) -> SFTRecord:
    tool_messages = tuple({
        "role": "assistant", "tool_call": call.action.model_dump(mode="json"),
        "tool_result": {"references": call.result_references, "summary": call.result_summary},
    } for call in episode.tool_calls)
    messages = ({"role": "user", "content": task.raw_message}, *tool_messages,
                {"role": "assistant", "content": episode.final_answer})
    normalized_payload = {
        "task": _normalized(task.raw_message),
        "actions": [call.action.model_dump(mode="json") for call in episode.tool_calls],
        "answer": _normalized(episode.final_answer),
    }
    digest = hashlib.sha256(json.dumps(normalized_payload, sort_keys=True,
                                      separators=(",", ":"), default=str).encode()).hexdigest()
    return SFTRecord(source_episode_id=episode.episode_id, task_id=task.id, split=task.split,
                     messages=messages, normalized_hash=digest)


def curate_survivors(
    episodes: tuple[EpisodeRecord, ...], tasks: dict[str, TaskSpec], catalog: CatalogProvider, *,
    catalog_hash: str, task_version: str, rule_version: str, created_at: dt.datetime,
    model_version: str = "unspecified-source-model",
) -> CurationResult:
    records: list[SFTRecord] = []
    exclusions: dict[str, str] = {}
    seen_hashes: set[str] = set()
    for episode in sorted(episodes, key=lambda item: item.episode_id):
        task = tasks.get(episode.task_id)
        reason = None
        if task is None: reason = "task_missing"
        elif task.split in {TaskSplit.TEST, TaskSplit.HELD_OUT_CATEGORY}: reason = "evaluation_leakage"
        elif episode.killed: reason = "killed"
        elif not _grounded(episode): reason = "grounding_failed"
        elif not _reviews_valid(episode, catalog): reason = "invalid_review_ids"
        if reason:
            exclusions[episode.episode_id] = reason
            continue
        item = _record(episode, task)
        if item.normalized_hash in seen_hashes:
            exclusions[episode.episode_id] = "duplicate_trace"
            continue
        seen_hashes.add(item.normalized_hash)
        records.append(item)
    content = [record.model_dump(mode="json") for record in records]
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    deduplication_hash = hashlib.sha256(
        "|".join(sorted(record.normalized_hash for record in records)).encode()
    ).hexdigest()
    manifest = TrainingManifest(
        catalog_hash=catalog_hash, task_version=task_version, rule_version=rule_version,
        model_version=model_version,
        source_episode_ids=tuple(record.source_episode_id for record in records),
        splits=tuple(sorted({record.split for record in records}, key=str)),
        source_task_splits={record.source_episode_id: record.split for record in records},
        deduplication_hash=deduplication_hash,
        created_at=created_at, content_hash=digest,
    )
    return CurationResult(tuple(records), manifest, exclusions)
