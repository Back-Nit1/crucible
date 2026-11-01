import datetime as dt
import json

import pytest

from modal_app.adapter_artifact import (ADAPTER_CONFIG, ADAPTER_WEIGHTS, AdapterFile, AdapterSelection, ArtifactError,
                                        ArtifactManifest, LineageEntry, Segment, hash_adapter_dir, load_manifest,
                                        seal_manifest, verify_adapter_dir, verify_selection, write_manifest)
from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION

H = "a" * 64
T = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.timezone.utc)


def write_adapter(directory, weights=b"weights-v1"):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ADAPTER_CONFIG).write_text('{"peft_type": "LORA"}')
    (directory / ADAPTER_WEIGHTS).write_bytes(weights)
    return hash_adapter_dir(directory)


def manifest(tmp_path, **over):
    files = write_adapter(tmp_path / "adapter")
    fields = dict(run_id="run-0001", base_model=MODEL_ID, base_revision=MODEL_REVISION, adapter_files=files,
                  training_manifest_hash="b" * 64, dataset_hash="c" * 64, dataset_record_count=30, plan_hash="d" * 64,
                  hyperparameters={"epochs": 1, "learning_rate": "0.0002"}, total_steps=6, steps_completed=6,
                  epochs_completed=1, checkpoint_lineage=(LineageEntry(step=3, epoch=0, state_sha256=H),),
                  segments=(Segment(start_step=0, end_step=3, duration_seconds=10.5),
                            Segment(start_step=3, end_step=6, duration_seconds=11.25)),
                  gpu="L4", cost_usd=None, cost_basis=None, created_at=T)
    return seal_manifest(**{**fields, **over})


def test_manifest_hashes_are_derived_and_round_trip_through_json(tmp_path):
    m = manifest(tmp_path)
    assert m.checkpoint_id == f"qwen-lora-{m.adapter_hash[:12]}" and m.adapter_path == "run-0001/final"
    assert m.duration_seconds == 21.75 and m.cost_usd is None  # unknown cost stays unknown
    write_manifest(m, tmp_path / "m.json")
    assert load_manifest(tmp_path / "m.json") == m
    assert manifest(tmp_path).manifest_hash == m.manifest_hash  # deterministic


def test_adapter_hash_ignores_listing_order_but_tracks_content(tmp_path):
    a = manifest(tmp_path)
    b = manifest(tmp_path, adapter_files=tuple(reversed(a.adapter_files)))
    assert a.adapter_hash == b.adapter_hash
    other = tmp_path / "other"
    write_adapter(other, weights=b"weights-v2")
    assert manifest(tmp_path, adapter_files=hash_adapter_dir(other)).adapter_hash != a.adapter_hash


def test_tampered_manifest_fields_are_rejected(tmp_path):
    m = manifest(tmp_path)
    data = m.model_dump(mode="json")
    for key, value in (("dataset_record_count", 31), ("gpu", "H100"), ("steps_completed", 6, ), ("training_manifest_hash", "e" * 64)):
        bad = {**data, key: value}
        if bad == data:
            continue
        with pytest.raises(ValueError):
            ArtifactManifest.model_validate(bad)
    with pytest.raises(ValueError):
        ArtifactManifest.model_validate({**data, "checkpoint_id": "qwen-lora-" + "0" * 12})


def test_incomplete_run_cannot_be_final(tmp_path):
    with pytest.raises(ValueError, match="incomplete"):
        manifest(tmp_path, steps_completed=5)


def test_requires_weights_and_config_and_rejects_pickles_and_traversal(tmp_path):
    only_config = (AdapterFile(path=ADAPTER_CONFIG, sha256=H, size_bytes=1), AdapterFile(path="x.json", sha256=H, size_bytes=1))
    with pytest.raises(ValueError, match="must contain"):
        manifest(tmp_path, adapter_files=only_config)
    for bad in ("../escape.safetensors", "/abs/adapter.safetensors", "optimizer.pt", "a\\b"):
        with pytest.raises(ValueError):
            AdapterFile(path=bad, sha256=H, size_bytes=1)


def test_cost_must_be_known_with_basis_or_unknown_with_none(tmp_path):
    with pytest.raises(ValueError, match="cost_usd"):
        manifest(tmp_path, cost_usd="0.05", cost_basis=None)
    assert manifest(tmp_path, cost_usd="0.05", cost_basis="measured seconds x list rate").cost_usd == "0.05"


def test_segments_must_be_contiguous_and_cover_all_steps(tmp_path):
    with pytest.raises(ValueError, match="contiguous|cover"):
        manifest(tmp_path, segments=(Segment(start_step=0, end_step=2, duration_seconds=1),
                                     Segment(start_step=3, end_step=6, duration_seconds=1)))


def test_selection_is_verified_against_pinned_base_and_hashes(tmp_path):
    m = manifest(tmp_path)
    sel = m.selection
    verify_selection(m, sel, base_model=MODEL_ID, base_revision=MODEL_REVISION)
    cases = [(sel, "other/model", MODEL_REVISION, "base_model_mismatch"),
             (sel, MODEL_ID, "f" * 40, "base_model_mismatch"),
             (sel.model_copy(update={"adapter_hash": "0" * 64}), MODEL_ID, MODEL_REVISION, "adapter_hash_mismatch"),
             (sel.model_copy(update={"training_manifest_hash": "0" * 64}), MODEL_ID, MODEL_REVISION, "training_manifest_mismatch"),
             (sel.model_copy(update={"run_id": "run-9999"}), MODEL_ID, MODEL_REVISION, "run_id_mismatch")]
    for selection, model, revision, code in cases:
        with pytest.raises(ArtifactError) as err:
            verify_selection(m, selection, base_model=model, base_revision=revision)
        assert err.value.code == code


def test_adapter_dir_verification_detects_alteration_missing_and_extra_files(tmp_path):
    m = manifest(tmp_path)
    directory = tmp_path / "adapter"
    verify_adapter_dir(m, directory)
    (directory / ADAPTER_WEIGHTS).write_bytes(b"corrupt")
    with pytest.raises(ArtifactError) as err:
        verify_adapter_dir(m, directory)
    assert err.value.code == "adapter_content_mismatch"
    (directory / ADAPTER_WEIGHTS).write_bytes(b"weights-v1")
    (directory / "extra.json").write_text("{}")
    with pytest.raises(ArtifactError) as err:
        verify_adapter_dir(m, directory)
    assert err.value.code == "adapter_files_mismatch"
    with pytest.raises(ArtifactError) as err:
        verify_adapter_dir(m, tmp_path / "nowhere")
    assert err.value.code == "adapter_missing"


def test_selection_rejects_path_like_run_ids():
    for bad in ("../x", "a/b", "ab", "UPPER", ""):
        with pytest.raises(ValueError):
            AdapterSelection(run_id=bad, adapter_hash=H, training_manifest_hash=H)


def test_load_manifest_reports_only_the_error_class(tmp_path):
    (tmp_path / "m.json").write_text(json.dumps({"run_id": "secret-looking-value"}))
    with pytest.raises(ArtifactError) as err:
        load_manifest(tmp_path / "m.json")
    assert "secret-looking-value" not in str(err.value) and err.value.code == "invalid_manifest"
