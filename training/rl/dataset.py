"""Rollouts (training.rollouts, crucible-rollout-v1) -> one deterministic, content-addressed crucible-grpo-v1 shard.

Laptop side, like training.dataset: every refusal is fail-closed with a stable code. Advantages are computed HERE and
sealed into the shard bytes, so the container trains on exactly what was hashed and approved. Refused:
  * duplicate episodes, an empty set (protected-split rollouts, test / held-out category, are excluded first and
    counted, exactly as curation excludes them: they never reach the shard, the rollout set hash or the audit input);
  * scripted rollouts unless allow_scripted (they read the answer key: pipeline evidence only);
  * stale rollouts: any rollout not produced by the checkpoint this run updates (cfg.policy_*), i.e. off-policy data;
  * memory-enabled rollouts: their stored prompts omit the retrieved examples, so log-probs would be off-prompt;
  * groups smaller than cfg.min_group_size; turns whose prompts are not prefixes of the episode.
A row is the full episode rendered through the inference converter (to_qwen_messages) with one advantage per
assistant turn; rows whose every turn has advantage 0 carry no gradient and are dropped (counted)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from agents.model import Message, action_tools
from agents.prompts import PROMPT_VERSION, system_prompt
from agents.qwen_client import qwen_tools, to_qwen_messages
from training.curation import TrainingManifest
from training.dataset import ALLOWED_SPLITS, DEFAULT_PROMPT_VARIANT, DatasetError, TrainingDataset, _assert_no_pii
from training.planning import GRPOConfig
from training.rl.advantage import episode_reward, turn_advantages
from training.rollouts import RolloutRecord
from training.shard import GRPO_FORMAT

__all__ = ["GRPO_FORMAT", "RLDataset", "build_rl_dataset", "rollout_set_hash"]


@dataclass(frozen=True)
class RLDataset:
    dataset: TrainingDataset
    manifest: TrainingManifest   # derived from the rollouts; content_hash = rollout_set_hash (approval + leakage audit bind it)
    stats: dict[str, int]


def _canonical(rollouts: Sequence[RolloutRecord]) -> list[RolloutRecord]:
    return sorted(rollouts, key=lambda r: r.episode_id)


def rollout_set_hash(rollouts: Sequence[RolloutRecord]) -> str:
    body = [r.model_dump(mode="json") for r in _canonical(rollouts)]
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _check(rollouts: list[RolloutRecord], cfg: GRPOConfig, allow_scripted: bool) -> dict[str, list[RolloutRecord]]:
    if not rollouts:
        raise DatasetError("empty_rollouts", "no rollouts to learn from")
    ids = [r.episode_id for r in rollouts]
    if len(set(ids)) != len(ids):
        raise DatasetError("duplicate_episode", "a rollout episode appears twice")
    groups: dict[str, list[RolloutRecord]] = {}
    for r in rollouts:
        if r.scripted and not allow_scripted:
            raise DatasetError("scripted_traces", "scripted (oracle) rollouts; pass --allow-scripted-traces for pipeline evidence only")
        if r.adapter_hash != cfg.policy_adapter_hash or (not r.scripted and r.model_checkpoint != cfg.policy_checkpoint):
            raise DatasetError("stale_rollouts", f"{r.episode_id} was produced by {r.model_checkpoint}, not {cfg.policy_checkpoint}")
        if r.memory_enabled:
            raise DatasetError("inexact_prompt", f"{r.episode_id}: memory-enabled rollouts do not store their full prompt")
        last = r.turns[-1].messages if r.turns else ()
        if any(t.index != i or last[:len(t.messages)] != t.messages for i, t in enumerate(r.turns)):
            raise DatasetError("malformed_rollout", f"{r.episode_id}: turn prompts are not prefixes of the episode")
        groups.setdefault(r.group_id, []).append(r)
    if any(len(g) < cfg.min_group_size for g in groups.values()):
        raise DatasetError("group_too_small", f"every group needs at least {cfg.min_group_size} samples")
    return groups


def _row(r: RolloutRecord, advantages: tuple[float, ...]) -> dict[str, object]:
    call = r.turns[-1].tool_call
    history = (*r.turns[-1].messages, Message(role="assistant", tool_name=call.name, tool_arguments=call.arguments))
    system = r.system_prompt if r.system_prompt is not None else system_prompt(DEFAULT_PROMPT_VARIANT)  # scripted fixtures only
    return {"source_episode_id": r.episode_id, "group_id": r.group_id, "system": system,
            "messages": to_qwen_messages(history), "turn_advantages": list(advantages)}


def build_rl_dataset(rollouts: Sequence[RolloutRecord], cfg: GRPOConfig, *, created_at: dt.datetime,
                     allow_scripted: bool = False) -> RLDataset:
    ordered = [r for r in _canonical(rollouts) if r.split in ALLOWED_SPLITS]
    groups = _check(ordered, cfg, allow_scripted)
    advantage: dict[str, tuple[float, ...]] = {}
    zero_variance = 0
    for members in groups.values():
        zero_variance += len({episode_reward(r, floor=cfg.reward_floor) for r in members}) == 1
        for r, adv in zip(members, turn_advantages(members, floor=cfg.reward_floor, weights=cfg.step_credit)):
            advantage[r.episode_id] = adv
    rows = [_row(r, advantage[r.episode_id]) for r in ordered if any(advantage[r.episode_id])]
    set_hash = rollout_set_hash(ordered)
    sources = sorted({r.model_version for r in ordered})
    source = ",".join(sources)
    header = {"header": {"format": GRPO_FORMAT, "training_manifest_hash": set_hash, "record_count": len(rows),
                         "source_model_version": source, "scripted": any(r.scripted for r in ordered),
                         "prompt_version": PROMPT_VERSION, "system": "", "tools": qwen_tools(action_tools())}}
    if not rows:
        raise DatasetError("no_signal", "every group has equal rewards and no turn penalties: nothing to learn")
    lines = [header, *rows]
    shard = ("\n".join(json.dumps(line, sort_keys=True, separators=(",", ":")) for line in lines) + "\n").encode()
    _assert_no_pii(json.dumps([[row["system"], row["messages"]] for row in rows]))  # advantages are floats, not text
    stats = {"rollouts": len(ordered), "groups": len(groups), "zero_variance_groups": zero_variance,
             "killed": sum(r.killed for r in ordered), "unscored": sum(r.fitness is None and not r.killed for r in ordered),
             "rows": len(rows), "dropped_no_signal": sum(1 for r in ordered if r.turns and not any(advantage[r.episode_id])),
             "dropped_no_turns": sum(not r.turns for r in ordered), "excluded_protected_split": len(rollouts) - len(ordered)}
    manifest = TrainingManifest(
        catalog_hash="unrecorded-in-rollouts", task_version="unrecorded-in-rollouts", rule_version="unrecorded-in-rollouts",
        model_version=source, source_episode_ids=tuple(r.episode_id for r in ordered),
        splits=tuple(sorted({r.split for r in ordered}, key=str)),
        source_task_splits={r.episode_id: r.split for r in ordered},
        deduplication_hash=hashlib.sha256("|".join(r.episode_id for r in ordered).encode()).hexdigest(),
        created_at=created_at, content_hash=set_hash)
    return RLDataset(TrainingDataset(shard=shard, dataset_hash=hashlib.sha256(shard).hexdigest(), record_count=len(rows),
                                     training_manifest_hash=set_hash), manifest, stats)
