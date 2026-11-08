# Crucible Observatory

## Product idea

The Observatory is the visual layer for Crucible's evolutionary commerce world. It does not
replace the existing evidence dashboards. It makes the project's core claim understandable to a
hackathon audience: Crucible rebuilds the internet as a controlled training ground where Qwen
shopping agents learn to research, reason, refuse, and buy safely.

The primary objects are virtual shops, not database records. Each shop represents an e-commerce
category and contains its real catalog listings as orbiting inventory. A central search exchange
represents catalog and review retrieval. A checkout/refusal gate represents budget enforcement,
quote validation, human confirmation, and the option to decline an impossible mission. Agents are
visible shoppers with a natural-language mission and wallet.

The visual rule is strict: every effect must map to recorded data. Distance, motion, color, trails,
and impacts cannot imply facts that the backend did not emit.

## What the first slice does

The `/observatory` route is an honest replay experience driven by the existing generation and
episode APIs. It provides:

- a 3D e-commerce internet built from virtual shops and real product references;
- a visible pool of Qwen shopper policies with rewards, survivor state, and kill outcomes;
- a plain-language mission card, shopper wallet, reward contract, and instant-fail conditions;
- an ordered playback that translates tool calls into understandable world actions;
- shop, product, and shopper selection;
- a visible world → scoring → selection → QLoRA/GRPO → Qwen 2.5 7B → redeploy loop;
- play, pause, step, timeline, and speed controls;
- an explicit `RECORDED REPLAY` / `SCRIPTED PIPELINE` label when that is the source.

This proves the visual language without claiming that a model is reacting live. Scripted archives
are explicitly labelled as world-engine evidence rather than Qwen performance.

## Lean frontend stack

- **Next.js + React:** the existing application shell, routes, server data loading, and evidence
  pages stay intact.
- **React Three Fiber + Three.js:** renders the product universe and agents inside React.
- **Drei:** supplies reliable camera controls, labels, lines, and star fields.
- **React Three Postprocessing:** adds restrained bloom so consequential events read instantly.
- **Zustand:** holds high-frequency playback and selection state outside the ordinary React page
  tree.
- **React Flow (later):** becomes the 2D world editor. It will produce a JSON experiment spec;
  Python remains responsible for validating and executing that spec.

Rapier, a second graph renderer, multiplayer infrastructure, XR, and cinematic authoring are
deliberately deferred. The replay is trace-driven, so physics would not improve determinism.

## How users will see learning

There are two different loops and the interface must never blur them:

1. **Generation evolution:** a short loop where genomes run tasks, fail or survive, and produce a
   mutated next population. This can eventually be watched live.
2. **Model training:** a long loop where grounded traces are curated, a model is trained, protected
   evaluations run, and a sealed checkpoint returns to the arena. This belongs in a background
   "forge" with job state and evaluation gates.

The Observatory should make changes legible through persistent trails, rejected regions, kill-rule
scars, parent/child lineage, and side-by-side generation ghosts. A number changing is not enough;
the user should be able to replay the behavior that caused it.

## Reality modes

- **Snapshot:** immutable catalog evidence. Reproducible and eligible for evaluation.
- **Sandbox:** user-authored perturbations layered over a pinned snapshot. Reproducible but kept
  separate from protected evaluation.
- **Synthetic frontier:** generated stress tests. Never allowed into curation or evaluation without
  an explicit, audited promotion step.

## Next contracts

Live generations need a backend-owned event stream, ideally SSE for the initial single-director
experience. A minimal event envelope is:

```json
{
  "experiment_id": "exp-...",
  "generation_id": "gen-...",
  "tick": 42,
  "seed": 20261101,
  "type": "tool.completed",
  "entity_id": "genome-...",
  "payload": {}
}
```

The later world editor should submit a versioned world spec containing the pinned base snapshot,
perturbation nodes, task derivation rules, kill-rule versions, random seed, and isolation class.
The backend validates the spec, builds an overlay catalog, re-derives feasible sets, executes the
world, and emits the same event protocol used for replay.
