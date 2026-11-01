from decimal import Decimal

import pytest

from agents.model import QwenModelAdapter
from agents.qwen_client import ModalQwenClient
from modal_app.adapter_artifact import MANIFEST_FILENAME, write_manifest
from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION
from tests.test_qwen_adapter_inference import T, make_artifact
from training.checkpoints import (BASE_LABEL, CheckpointCatalog, CheckpointError, artifact_ref, selection_from_ref)
from world.evolution import Genome
from world.runtime import build_population, compat_for, model_policy_id


@pytest.fixture
def two(tmp_path):
    a = make_artifact(tmp_path, run_id="run-aaaa", weights=b"A")
    b = make_artifact(tmp_path, run_id="run-bbbb", weights=b"B")
    return a, b, CheckpointCatalog([a, b])


def genome(label):
    return build_population(2, 5, fixtures=False, checkpoint=label)[0]


def test_labels_and_selection_for_base_and_each_adapter(two):
    a, b, catalog = two
    assert catalog.labels() == (BASE_LABEL, *sorted([a.checkpoint_id, b.checkpoint_id]))
    assert catalog.selection_for(BASE_LABEL) is None
    assert catalog.selection_for(a.checkpoint_id) == a.selection != catalog.selection_for(b.checkpoint_id)


def test_scripted_and_unknown_labels_are_refused_never_substituted_with_base(two):
    _, _, catalog = two
    for label, code in (("scripted-v1", "not_a_model_checkpoint"), ("qwen-lora-" + "0" * 12, "unknown_checkpoint")):
        with pytest.raises(CheckpointError) as err:
            catalog.selection_for(label)
        assert err.value.code == code


def test_adapter_trained_on_another_base_or_manifest_is_rejected(tmp_path, two):
    a, _, catalog = two
    with pytest.raises(CheckpointError) as err:
        CheckpointCatalog([make_artifact(tmp_path, run_id="run-cccc", base_revision="f" * 40)])
    assert err.value.code == "incompatible_base"
    assert catalog.selection_for(a.checkpoint_id, expected_training_manifest_hash=a.training_manifest_hash) == a.selection
    with pytest.raises(CheckpointError) as err:
        catalog.selection_for(a.checkpoint_id, expected_training_manifest_hash="9" * 64)
    assert err.value.code == "training_manifest_mismatch"


def test_manifest_files_are_verified_on_load(tmp_path, two):
    a, _, _ = two
    path = tmp_path / "run-aaaa" / "final" / MANIFEST_FILENAME
    assert CheckpointCatalog.from_manifest_files([path]).labels()[1] == a.checkpoint_id
    path.write_text(path.read_text().replace('"gpu": "L4"', '"gpu": "H100"'))
    with pytest.raises(CheckpointError) as err:
        CheckpointCatalog.from_manifest_files([path])
    assert err.value.code == "invalid_manifest"


def test_adapter_for_builds_one_pinned_client_per_checkpoint(two):
    a, b, catalog = two
    made = []

    def make_client(selection):
        made.append(selection)
        return ModalQwenClient(lambda p, t: {}, cost_ceiling=Decimal("1"), adapter=selection)

    adapter_for = catalog.adapter_for(make_client)
    base_g, a_g, b_g = genome(BASE_LABEL), genome(a.checkpoint_id), genome(b.checkpoint_id)
    first = adapter_for(a_g)
    assert isinstance(first, QwenModelAdapter) and adapter_for(genome(a.checkpoint_id)) is first
    adapter_for(base_g)
    adapter_for(b_g)
    assert made == [a.selection, None, b.selection]
    assert first.client.checkpoint_label == a.checkpoint_id
    with pytest.raises(CheckpointError):
        adapter_for(genome("scripted-v1"))


def test_resume_compatibility_includes_model_and_adapter_identity(two):
    a, b, _ = two
    ids = {model_policy_id("qwen", label) for label in (BASE_LABEL, a.checkpoint_id, b.checkpoint_id)}
    assert len(ids) == 3
    assert model_policy_id("qwen", a.checkpoint_id) != "scripted-v1"
    manifests = {"cat": "h"}
    base_pop, a_pop = (build_population(2, 5, fixtures=False, checkpoint=c) for c in (BASE_LABEL, a.checkpoint_id))
    base_compat = compat_for((), base_pop, manifests, model_policy_id("qwen", BASE_LABEL))
    adapter_compat = compat_for((), a_pop, manifests, model_policy_id("qwen", a.checkpoint_id))
    assert base_compat != adapter_compat and adapter_compat.population_hash != base_compat.population_hash


def test_artifact_ref_is_content_addressed_and_round_trips(two):
    a, _, _ = two
    ref = artifact_ref(a)
    assert ref == f"modal-volume://crucible-qwen-adapters/runs/run-aaaa/final@{a.adapter_hash}"
    assert selection_from_ref(ref, training_manifest_hash=a.training_manifest_hash) == a.selection
    for bad in ("modal-volume://other/runs/run-aaaa/final@" + a.adapter_hash, ref + "x", ref.replace("run-aaaa", "../x")):
        with pytest.raises(CheckpointError):
            selection_from_ref(bad, training_manifest_hash=a.training_manifest_hash)
