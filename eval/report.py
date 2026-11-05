"""Honest JSON + Markdown evaluation report from a completed manifest. Numbers come only from stored episode artifacts."""
from __future__ import annotations

import datetime as dt
import json
import statistics
from decimal import Decimal

from eval.comparison import ContenderRun, compare_contenders
from eval.harness import _successful, calculate_metrics
from eval.leakage import AuditReport
from eval.manifest import EvaluationManifest
from eval.runner import EvaluationStore, complete_artifacts
from eval.webshop import WebShopResult, blocked
from tasks.schemas import TaskSpec

REPORT_VERSION = "1.0"
CAVEATS = (
    "Payments: MockPayments only (no PayPal sandbox call was made); purchases are simulated against a frozen catalog.",
    "Prices are Amazon-2023 snapshot prices from the frozen catalog, not live prices.",
    "Cost is the list-rate estimate from the inference client; Modal billing is authoritative.",
    "Variance is the population variance of the per-seed metric value across the listed seeds (None with one seed).",
)


class NotAMeasurement(ValueError):
    """The episodes came from a scripted shopper or test double, not a model: they cannot be reported as model performance."""


def _num(d: Decimal | None) -> str | None:
    return None if d is None else str(d)


def _metric(m, variance) -> dict:
    return {"numerator": str(m.numerator), "denominator": str(m.denominator), "excluded": m.excluded, "value": _num(m.value),
            "unit": m.unit, "variance_across_seeds": _num(variance), "failure_reasons": m.failure_reasons}


def _fitness(eps) -> dict:
    """Mean fitness over scored episodes; unscored ones (model failure, tool limit) are excluded, never counted as 0."""
    values = [Decimal(str(e.score_components["fitness"])) for e in eps if "fitness" in e.score_components]
    total = sum(values, Decimal(0))
    return {"numerator": str(total), "denominator": str(len(values)), "excluded": len(eps) - len(values),
            "value": _num((total / len(values)).quantize(Decimal("0.000001")) if values else None), "unit": "mean_fitness"}


def _kill_rate(eps) -> dict:
    killed = sum(e.killed for e in eps)
    return {"numerator": str(killed), "denominator": str(len(eps)), "excluded": 0,
            "value": _num((Decimal(killed) / len(eps)).quantize(Decimal("0.000001")) if eps else None), "unit": "rate"}


def _delta(this: dict, base: dict) -> str | None:
    return None if this["value"] is None or base["value"] is None else str(Decimal(this["value"]) - Decimal(base["value"]))


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def build_report(manifest: EvaluationManifest, store: EvaluationStore, tasks: dict[str, TaskSpec], *,
                 audit: AuditReport, exclusions: dict[str, str] | None = None,
                 webshop: dict[str, WebShopResult] | None = None, allow_test_double: bool = False,
                 now: dt.datetime | None = None) -> dict:
    artifacts = complete_artifacts(manifest, store)
    models = {str(m.get("model")) for a in artifacts.values() for m in a.episode.model_metadata}
    checkpoints = {a.episode.agent_id for a in artifacts.values()}
    double = any(m == "scripted" or m.startswith("scripted") for m in models) or any(c.startswith("scripted") for c in checkpoints)
    if double and not allow_test_double:
        raise NotAMeasurement("episodes were produced by a scripted shopper/test double, not a model")
    runs = tuple(ContenderRun(contender_id=c.id, checkpoint=c.checkpoint, memory_enabled=c.memory_enabled,
                              training_manifest_hash=c.training_manifest_hash,
                              episodes=tuple(artifacts[(c.id, t, s)].episode for t, s in manifest.pairs)) for c in manifest.contenders)
    comparison = compare_contenders(runs, tasks, pass_k=manifest.pass_k)   # enforces identical task/seed pairs
    base = next((r for r in runs if r.contender_id == "base-qwen"), None)
    held = sorted({t.category for t in manifest.tasks if t.held_out_category})
    base_fitness, base_kill_rate = (_fitness(base.episodes), _kill_rate(base.episodes)) if base else (None, None)
    contenders = []
    for cfg, result, run in zip(manifest.contenders, comparison.contenders, runs):
        ev = result.evaluation
        eps = list(run.episodes)
        wall = [artifacts[(cfg.id, t, s)].wall_seconds for t, s in manifest.pairs]
        steps = [m for e in eps for m in e.model_metadata]
        per_seed = {str(seed): _metric(calculate_metrics(tuple(e for e in eps if e.seed == seed), tasks, pass_k=1,
                                                         include_variance=False).metrics["success_rate"], None)
                    for seed in manifest.seeds}
        paired = None
        if base is not None and base is not run:
            b = {(e.task_id, e.seed): e for e in base.episodes}
            ok = _successful  # the one success definition
            paired = {"both_succeed": sum(ok(e) and ok(b[(e.task_id, e.seed)]) for e in eps),
                      "only_this_succeeds": sum(ok(e) and not ok(b[(e.task_id, e.seed)]) for e in eps),
                      "only_base_succeeds": sum(not ok(e) and ok(b[(e.task_id, e.seed)]) for e in eps),
                      "neither": sum(not ok(e) and not ok(b[(e.task_id, e.seed)]) for e in eps), "pairs": len(eps)}
        fitness, kill_rate = _fitness(eps), _kill_rate(eps)
        contenders.append({
            "fitness": fitness, "kill_rate": kill_rate,
            "vs_base": None if base is None or base is run else {
                "fitness_delta": _delta(fitness, base_fitness), "kill_rate_delta": _delta(kill_rate, base_kill_rate)},
            "contender": cfg.model_dump(mode="json"), "identity_hash": cfg.identity_hash, "checkpoint": cfg.checkpoint,
            "metrics": {n: _metric(m, ev.variance_across_seeds.get(n)) for n, m in sorted(ev.metrics.items())},
            "success_rate_by_seed": per_seed,
            "latency": {"model_inference_ms_mean": _num(ev.metrics["latency_ms"].value),
                        "episodes_with_latency": str(ev.metrics["latency_ms"].denominator),
                        "wall_seconds_mean": round(statistics.fmean(wall), 6), "wall_seconds_p50": _percentile(wall, 0.5),
                        "wall_seconds_p95": _percentile(wall, 0.95), "wall_seconds_total": round(sum(wall), 6), "episodes": len(wall)},
            "cost": {"total_usd_estimate": str(sum((e.cost for e in eps), Decimal(0))), "per_task": _metric(ev.metrics["cost_per_task"], None),
                     "steps_with_unknown_cost": sum(m.get("cost_known") is False for m in steps), "model_steps": len(steps),
                     "tokens": sum(e.token_count for e in eps)},
            "failure_counts": {"episodes": len(eps), **{k: sum(e.termination == k for e in eps) for k in
                               ("success", "no_match", "instant_kill", "malformed_action", "tool_limit", "model_failure")},
                               "killed": sum(e.killed for e in eps),
                               "quarantined_backend_failures": len(store.load_episodes(manifest, quarantine=True)) if cfg.id == manifest.contenders[0].id else None},
            "paired_vs_base": paired,
            "webshop": (webshop or {}).get(cfg.id, blocked(cfg, ["WebShop was not run for this contender"], now or dt.datetime.now(dt.UTC))).model_dump(mode="json"),
        })
    return {
        "report_version": REPORT_VERSION, "evidence_class": "test_double_not_a_measurement" if double else "measured_model",
        "evaluation_id": manifest.evaluation_id, "manifest_hash": manifest.manifest_hash, "manifest_status": (store.load_manifest() or manifest).status.value,
        "generated_at": (now or dt.datetime.now(dt.UTC)).isoformat(), "created_at": manifest.created_at.isoformat(),
        "payment_backend": manifest.payment_backend, "price_basis": "frozen Amazon snapshot prices (not live)",
        "task_set_hash": manifest.task_set_hash, "catalog_hash": manifest.catalog_hash, "seeds": list(manifest.seeds),
        "pass_k": manifest.pass_k, "task_count": len(manifest.tasks), "pairs": len(manifest.pairs),
        "split_counts": {s: sum(t.split == s for t in manifest.tasks) for s in sorted({t.split for t in manifest.tasks})},
        "held_out_categories": held, "versions": manifest.versions.model_dump(mode="json"),
        "memory": {"pool_hash": manifest.memory_pool_hash, "pool_size": manifest.memory_pool_size},
        "leakage_audit": {"passed": audit.passed, "content_hash": audit.content_hash,
                          "checks": {n: {"status": c.status, "examined": c.examined, "violations": c.violations} for n, c in audit.checks.items()}},
        "exclusions": {"task_text_duplicates": exclusions or {}, "count": len(exclusions or {})},
        "expected_records": manifest.expected_records, "unique_records": len(artifacts),
        "contenders": contenders, "caveats": list(CAVEATS),
    }


def to_markdown(report: dict) -> str:
    out = [f"# Crucible evaluation `{report['evaluation_id']}`", "",
           f"**Evidence class: `{report['evidence_class']}`** · payments: {report['payment_backend']} · {report['price_basis']}", "",
           f"- manifest `{report['manifest_hash'][:16]}…` · task set `{report['task_set_hash'][:16]}…` · catalog `{report['catalog_hash'][:16]}…`",
           f"- {report['task_count']} tasks × {len(report['seeds'])} seeds {report['seeds']} = {report['pairs']} identical (task, seed) pairs per contender; "
           f"{report['unique_records']}/{report['expected_records']} records; pass@{report['pass_k']}",
           f"- splits {report['split_counts']}; held-out categories {report['held_out_categories'] or 'none'}",
           f"- leakage audit: **{'PASSED' if report['leakage_audit']['passed'] else 'FAILED'}** `{report['leakage_audit']['content_hash'][:12]}`; "
           f"task-text duplicates excluded: {report['exclusions']['count']}", ""]
    names = sorted({n for c in report["contenders"] for n in c["metrics"]})
    for c in report["contenders"]:
        cfg = c["contender"]
        out += [f"## {cfg['id']}", "",
                f"`{c['checkpoint']}` · memory {'on (k=%d)' % cfg['memory_k'] if cfg['memory_enabled'] else 'off'} · prompt `{cfg['prompt_version']}` · "
                f"temperature {cfg['temperature']} · training manifest `{cfg['training_manifest_hash'] or 'none'}`", "",
                "| Metric | Num | Den | Excl | Value | Var (seeds) | Unit | Why not counted / failed |", "|---|---:|---:|---:|---:|---:|---|---|"]
        for n in names:
            m = c["metrics"][n]
            out.append(f"| {n} | {m['numerator']} | {m['denominator']} | {m['excluded']} | {m['value'] if m['value'] is not None else 'N/A'} | "
                       f"{m['variance_across_seeds'] if m['variance_across_seeds'] is not None else 'N/A'} | {m['unit']} | "
                       f"{', '.join(f'{k}={v}' for k, v in m['failure_reasons'].items()) or '-'} |")
        lat, cost, fc = c["latency"], c["cost"], c["failure_counts"]
        out += ["", f"- latency: model inference mean {lat['model_inference_ms_mean'] or 'N/A'} ms over {lat['episodes_with_latency']} episodes; "
                    f"wall mean {lat['wall_seconds_mean']}s, p95 {lat['wall_seconds_p95']}s",
                f"- cost: ${cost['total_usd_estimate']} estimated total, {cost['steps_with_unknown_cost']}/{cost['model_steps']} steps with unknown cost",
                f"- failures: {fc}", ""]
        out.append(f"- fitness {c['fitness']['value'] or 'N/A'} ({c['fitness']['denominator']} scored, {c['fitness']['excluded']} excluded); "
                   f"kill rate {c['kill_rate']['value'] or 'N/A'} ({c['kill_rate']['numerator']}/{c['kill_rate']['denominator']})"
                   + (f"; vs base-qwen: fitness {c['vs_base']['fitness_delta'] or 'N/A'}, kill rate {c['vs_base']['kill_rate_delta'] or 'N/A'}"
                      if c["vs_base"] else ""))
        if c["paired_vs_base"]:
            out += [f"- paired vs base-qwen: {c['paired_vs_base']}", ""]
        w = c["webshop"]
        out += [f"- WebShop: **{w['status']}**" + (f" — {w['not_run_reason']}" if w["status"] == "blocked_not_run" else
                f" — reward {w['mean_reward']} ({w['success_numerator']}/{w['denominator']} perfect, {w['excluded']} excluded, "
                f"{'full 500-session benchmark' if w['full_benchmark'] else 'SUBSET: not comparable to published scores'})"), ""]
    out += ["## Caveats", "", *(f"- {c}" for c in report["caveats"]), ""]
    return "\n".join(out)


def write_report(report: dict, directory, stem: str):
    from pathlib import Path
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{stem}.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    (root / f"{stem}.md").write_text(to_markdown(report))
    return root / f"{stem}.json", root / f"{stem}.md"
