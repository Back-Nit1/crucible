"""Evaluation manifest: strict identity, canonical hash, identical task/seed matrix, placeholder rejection."""
import datetime as dt
import json
from decimal import Decimal

import pytest

from eval.contenders import (AdapterReference, ContenderConfig, ContenderError, load_adapter_reference,
                             sha256_file, standard_contenders)
from eval.manifest import EvaluationManifest, Versions, assert_same_manifest, build_manifest
from tasks.schemas import TaskSplit
from tests.fixtures.scoring import feasible_task

NOW = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
REV = "a" * 40
H = "b" * 64
VERSIONS = Versions(prompt="shopper-prompts-v1", rules="K001:1", judge="none", task_generator="taskgen-v1")


def contenders(**kw):
    return standard_contenders(model_id="Qwen/Qwen2.5-7B-Instruct", base_revision=REV, prompt_version="shopper-prompts-v1",
                               endpoint="modal:crucible-qwen-inference/Qwen", **kw)


def manifest(seeds=(1, 2), pass_k=1, **kw):
    tasks = (feasible_task(id="t-1", split=TaskSplit.TEST), feasible_task(id="t-2", split=TaskSplit.TEST))
    return tasks, build_manifest(evaluation_id="eval-1", tasks=tasks, seeds=seeds, contenders=contenders(), catalog_hash="c" * 64,
                                 versions=VERSIONS, pass_k=pass_k, created_at=NOW, **kw)


@pytest.mark.parametrize("field,value", [("model_id", "qwen-base-placeholder"), ("endpoint", "TODO"), ("prompt_version", "tbd-v1")])
def test_placeholder_values_are_rejected(field, value):
    base = contenders()[0].model_dump()
    base[field] = value
    with pytest.raises(ValueError, match="placeholder"):
        ContenderConfig(**base)


def test_revision_must_be_a_real_commit_and_finetuned_needs_a_real_artifact():
    with pytest.raises(ValueError, match="40-hex"):
        ContenderConfig(id="x", kind="base", model_id="m", base_revision="main", memory_enabled=False,
                        prompt_version="p", temperature=Decimal(0), endpoint="e")
    with pytest.raises(ValueError, match="no fine-tuned artifact"):
        ContenderConfig(id="x", kind="finetuned", model_id="m", base_revision=REV, memory_enabled=False,
                        prompt_version="p", temperature=Decimal(0), endpoint="e")
    with pytest.raises(ValueError, match="not authorized"):
        ContenderConfig(id="f", kind="frontier", model_id="big", base_revision="2026-01", memory_enabled=False,
                        prompt_version="p", temperature=Decimal(0), endpoint="e")


def test_finetuned_contender_requires_an_existing_artifact_reference(tmp_path):
    with pytest.raises(ContenderError, match="has not been produced"):
        load_adapter_reference(tmp_path / "adapter_ref.json")
    artifact = tmp_path / "adapter.safetensors"
    artifact.write_bytes(b"weights")
    ref = AdapterReference(adapter_ref=str(artifact), adapter_sha256=sha256_file(artifact), base_model="Qwen/Qwen2.5-7B-Instruct",
                           base_revision=REV, training_manifest_hash=H)
    path = tmp_path / "adapter_ref.json"
    path.write_text(ref.model_dump_json())
    loaded = load_adapter_reference(path)
    ids = [c.id for c in contenders(adapter=loaded)]
    assert ids == ["base-qwen", "base-qwen-memory", "survivor-finetuned"]
    artifact.write_bytes(b"tampered")
    with pytest.raises(ContenderError, match="hash does not match"):
        load_adapter_reference(path)
    with pytest.raises(ContenderError, match="different base"):
        standard_contenders(model_id="Qwen/Qwen2.5-7B-Instruct", base_revision="c" * 40, prompt_version="p", endpoint="e",
                            adapter=loaded)


def test_manifest_hash_is_stable_and_ignores_run_state_only():
    tasks, m = manifest()
    again = EvaluationManifest.model_validate_json(m.model_dump_json())
    assert again.manifest_hash == m.manifest_hash
    assert m.with_state(status="running", result_artifacts={"a": "b"}).manifest_hash == m.manifest_hash
    _, other_seed = manifest(seeds=(1, 3))
    assert other_seed.manifest_hash != m.manifest_hash
    with pytest.raises(ValueError, match="different evaluation manifests"):
        assert_same_manifest(m.manifest_hash, other_seed.manifest_hash)


def test_identical_task_seed_matrix_and_counts():
    _, m = manifest()
    assert m.pairs == (("t-1", 1), ("t-1", 2), ("t-2", 1), ("t-2", 2))
    assert m.expected_records == 2 * 4 and m.resume.expected_records == 8


def test_manifest_rejects_incoherent_inputs():
    with pytest.raises(ValueError, match="at least k"):
        manifest(seeds=(1,), pass_k=2)
    with pytest.raises(ValueError, match="duplicate seeds"):
        manifest(seeds=(1, 1))
    tasks, m = manifest()
    data = json.loads(m.model_dump_json())
    data["resume"]["expected_records"] = 3
    with pytest.raises(ValueError, match="expected_records"):
        EvaluationManifest.model_validate(data)


def test_verify_tasks_detects_drift():
    tasks, m = manifest()
    by_id = {t.id: t for t in tasks}
    assert [t.id for t in m.verify_tasks(by_id)] == ["t-1", "t-2"]
    drifted = dict(by_id, **{"t-2": by_id["t-2"].model_copy(update={"catalog_manifest_hash": "other"})})
    with pytest.raises(ValueError, match="hash mismatch"):
        m.verify_tasks(drifted)
    with pytest.raises(ValueError, match="missing"):
        m.verify_tasks({"t-1": by_id["t-1"]})
