"""Rollout contract: one `RolloutRecord` per world episode — survivors, losers and killed alike — so every episode is
reusable data (SFT curation filters it, GRPO groups it). Schema owner: the expert-iteration loop (Agent A).

  rollout_from_episode(episode, task, genome, catalog=..., policy_id=..., iteration_id=..., sample_index=k)

`group_id` is deterministic from (task, policy checkpoint, iteration): K samples of one task under one checkpoint in one
iteration share it. Turn `messages` are the exact `agents.model.render_messages` conversation before that call
(ponytail: retrieved memory examples are not stored on the episode, so memory-enabled genomes' prompts omit them; record
them on the episode if GRPO ever needs exact memory prompts). Kill rules are episode-level and are attributed to the
terminal turn. `scripted=True` rollouts read the answer key: pipeline evidence only, never training data."""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agents.actions import EpisodeRecord, ProposePurchase, SummarizeReviewEvidence
from agents.model import Message, StructuredToolCall, render_messages
from catalog.providers.base import FrozenCatalogProvider
from memory.episodes import PRIVILEGED_CHECKPOINT_PREFIX
from tasks.schemas import TaskSpec, TaskSplit
from world.evolution import Genome
from world.store import digest

ROLLOUT_VERSION = "crucible-rollout-v1"


class RolloutModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RolloutTurn(RolloutModel):
    index: int = Field(ge=0)
    messages: tuple[Message, ...]  # rendered conversation the policy saw before this call
    tool_call: StructuredToolCall  # the assistant's call (action type + arguments)
    tool_result: dict[str, object]  # references, summary, error_code
    schema_valid: bool  # the executor accepted the call (no tool error)
    grounded: bool | None  # cited ids exist in the frozen catalog; None = the call cites nothing
    kill_rules: tuple[str, ...] = ()  # rule ids attributed to this turn


class RolloutRecord(RolloutModel):
    schema_version: Literal["crucible-rollout-v1"] = ROLLOUT_VERSION
    episode_id: str
    generation_id: str
    iteration_id: str | None
    task_id: str
    split: TaskSplit
    group_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_index: int = Field(ge=0)
    seed: int = Field(ge=0)
    genome_id: str
    model_checkpoint: str
    adapter_hash: str | None  # None = base model (or scripted policy)
    prompt_variant: str
    system_prompt: str | None  # None = fixture variant with no model prompt (scripted only)
    temperature: Decimal
    memory_enabled: bool
    model_version: str  # policy id that produced the episode
    scripted: bool
    turns: tuple[RolloutTurn, ...]
    termination: str
    gate: Literal[0, 1] | None  # None = unscored episode (model failure, tool limit, malformed)
    quality: Decimal | None
    efficiency_penalty: Decimal | None
    fitness: Decimal | None
    killed: bool
    kill_reasons: tuple[str, ...]


def group_id(task_id: str, checkpoint: str, iteration_id: str | None) -> str:
    return digest("rollout-group", task_id, checkpoint, iteration_id or "")


def _grounded(action, catalog: FrozenCatalogProvider) -> bool | None:
    if isinstance(action, SummarizeReviewEvidence):
        cited = {rid for claim in action.claims for rid in claim.review_ids}
        return bool(cited) and cited <= catalog.get_review_ids(action.product_id).ids
    if isinstance(action, ProposePurchase):
        return catalog.get_product(action.product_id) is not None
    return None


def rollout_from_episode(episode: EpisodeRecord, task: TaskSpec, genome: Genome, *, catalog: FrozenCatalogProvider,
                         policy_id: str, iteration_id: str | None = None, sample_index: int = 0,
                         adapter_hash: str | None = None) -> RolloutRecord:
    from agents.prompts import system_prompt
    from world.runtime import episode_seed
    try:
        prompt = system_prompt(genome.system_prompt_variant)
    except ValueError:
        prompt = None
    calls, kills = episode.tool_calls, tuple(str(k["rule_id"]) for k in episode.kill_information)
    turns = tuple(RolloutTurn(
        index=i, messages=render_messages(task, calls[:i]),
        tool_call=StructuredToolCall(name=c.action.type, arguments=c.arguments),
        tool_result={"references": list(c.result_references), "summary": c.result_summary, "error_code": c.error_code},
        schema_valid=c.error_code is None, grounded=_grounded(c.action, catalog),
        kill_rules=kills if i == len(calls) - 1 else ()) for i, c in enumerate(calls))
    sc = episode.score_components
    scored = "fitness" in sc
    return RolloutRecord(
        episode_id=episode.episode_id, generation_id=episode.generation_id, iteration_id=iteration_id, task_id=task.id,
        split=task.split, group_id=group_id(task.id, genome.model_checkpoint, iteration_id), sample_index=sample_index,
        seed=episode_seed(episode.seed, episode.episode_id.removeprefix(f"{episode.generation_id}:")), genome_id=genome.id, model_checkpoint=genome.model_checkpoint, adapter_hash=adapter_hash,
        prompt_variant=genome.system_prompt_variant, system_prompt=prompt, temperature=genome.temperature,
        memory_enabled=genome.memory.enabled, model_version=policy_id,
        scripted=genome.model_checkpoint.startswith(PRIVILEGED_CHECKPOINT_PREFIX), turns=turns,
        termination=episode.termination, gate=int(sc["gate"]) if scored else None,
        quality=Decimal(str(sc["quality"])) if scored else None,
        efficiency_penalty=Decimal(str(sc["efficiency_penalty"])) if scored else None,
        fitness=Decimal(str(sc["fitness"])) if scored else None, killed=episode.killed, kill_reasons=kills)


def write_rollouts(path, episodes, *, tasks: dict, genomes: dict, catalog: FrozenCatalogProvider, policy_id: str,
                   iteration_id: str | None = None, adapter_hash: str | None = None) -> int:
    """Every episode -> one JSONL line, ordered by episode id (byte-identical for identical runs)."""
    from pathlib import Path
    lines = [rollout_from_episode(e, tasks[e.task_id], genomes[e.agent_id], catalog=catalog, policy_id=policy_id,
                                  iteration_id=iteration_id, sample_index=sample_index(e.episode_id),
                                  adapter_hash=adapter_hash).model_dump_json() + "\n"
             for e in sorted(episodes, key=lambda e: e.episode_id)]
    Path(path).write_text("".join(lines))
    return len(lines)


def sample_index(episode_id: str) -> int:
    """`<gen>:<genome>:<task>` is sample 0; `...#<k>` is sample k (identifiers never contain '#')."""
    return int(episode_id.rpartition("#")[2]) if "#" in episode_id else 0
