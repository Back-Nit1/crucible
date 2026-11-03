import datetime as dt
import hashlib
import json

import pytest

from tasks.schemas import TaskSplit
from tests.fixtures.scoring import InMemoryCatalog
from tests.test_training_curation import successful_episode
from training.curation import curate_survivors
from training.dataset import DatasetError, build_dataset, curation_content_hash, render_example, validate_records


def curated():
    task, episode = successful_episode()
    result = curate_survivors((episode,), {task.id: task}, InMemoryCatalog(), catalog_hash="a" * 64, task_version="t1",
                              rule_version="k1", created_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    return result.records, result.manifest


def rebuilt(records, manifest):
    """A manifest that is internally consistent for `records` (what curation would have produced)."""
    return manifest.model_copy(update={
        "source_episode_ids": tuple(r.source_episode_id for r in records),
        "source_task_splits": {r.source_episode_id: r.split for r in records},
        "splits": tuple(sorted({r.split for r in records}, key=str)),
        "content_hash": curation_content_hash(records),
        "deduplication_hash": hashlib.sha256("|".join(sorted(r.normalized_hash for r in records)).encode()).hexdigest()})


def test_content_hash_helper_matches_what_curation_stores():
    records, manifest = curated()
    assert curation_content_hash(records) == manifest.content_hash
    validate_records(records, manifest)


def test_shard_is_deterministic_hash_addressed_and_binds_the_manifest():
    records, manifest = curated()
    a, b = build_dataset(records, manifest), build_dataset(records, manifest)
    assert a.shard == b.shard and a.dataset_hash == hashlib.sha256(a.shard).hexdigest()
    assert a.training_manifest_hash == manifest.content_hash and a.record_count == 1
    header, example = [json.loads(line) for line in a.shard.decode().splitlines()]
    assert header["header"]["training_manifest_hash"] == manifest.content_hash
    assert {t["function"]["name"] for t in header["header"]["tools"]} >= {"parse_intent", "confirm_and_pay"}
    assert example["source_episode_id"] == "ep-train"


def test_examples_use_the_inference_message_format_and_drop_synthesized_final_answer():
    records, _ = curated()
    messages = render_example(records[0])
    assert messages[0]["role"] == "user"
    calls = [m for m in messages if m.get("tool_calls")]
    assert [c["tool_calls"][0]["function"]["name"] for c in calls][:2] == ["parse_intent", "search_catalog"]
    assert all("type" not in c["tool_calls"][0]["function"]["arguments"] for c in calls)
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert len(tool_msgs) == len(calls) and '"error_code": null' in tool_msgs[0]["content"]
    assert messages[-1]["role"] == "tool"  # no trailing prose "Recommend ..." turn


def test_test_and_held_out_splits_are_rejected_even_if_the_manifest_lies():
    records, manifest = curated()
    for split in (TaskSplit.TEST, TaskSplit.HELD_OUT_CATEGORY):
        leaked = (records[0].model_copy(update={"split": split}),)
        with pytest.raises(DatasetError) as err:
            validate_records(leaked, rebuilt(leaked, manifest))
        assert err.value.code == "forbidden_split"
    lying = manifest.model_copy(update={"source_task_splits": {"ep-train": TaskSplit.TEST}})
    with pytest.raises(DatasetError) as err:
        validate_records(records, lying)
    assert err.value.code == "forbidden_split"


def test_validation_split_is_allowed_for_training():
    records, manifest = curated()
    val = (records[0].model_copy(update={"split": TaskSplit.VALIDATION}),)
    validate_records(val, rebuilt(val, manifest))


@pytest.mark.parametrize("mutate, code", [
    (lambda r, m: (r, m.model_copy(update={"content_hash": "0" * 64})), "manifest_hash_mismatch"),
    (lambda r, m: (r, m.model_copy(update={"deduplication_hash": "0" * 64})), "dedup_hash_mismatch"),
    (lambda r, m: (r, m.model_copy(update={"source_episode_ids": ("other",)})), "record_set_mismatch"),
    (lambda r, m: (r + r, m), "duplicate_episode"),
    (lambda r, m: ((), m), "empty_dataset"),
])
def test_manifest_and_count_mismatches_fail_closed(mutate, code):
    records, manifest = curated()
    with pytest.raises(DatasetError) as err:
        validate_records(*mutate(records, manifest))
    assert err.value.code == code


def test_edited_record_content_no_longer_matches_manifest():
    records, manifest = curated()
    edited = (records[0].model_copy(update={"messages": ({"role": "user", "content": "different"}, *records[0].messages[1:])}),)
    with pytest.raises(DatasetError) as err:
        validate_records(edited, manifest)
    assert err.value.code == "manifest_hash_mismatch"


@pytest.mark.parametrize("pii", ["mail me at jane.doe@example.com", "call 415-555-0134 please", "card 4111111111111111"])
def test_pii_shaped_values_are_refused(pii):
    records, manifest = curated()
    leaky = (records[0].model_copy(update={"messages": ({"role": "user", "content": pii}, *records[0].messages[1:])}),)
    with pytest.raises(DatasetError) as err:
        build_dataset(leaky, rebuilt(leaky, manifest))
    assert err.value.code == "pii_detected" and "example.com" not in str(err.value)


def test_budget_numbers_and_sizes_are_not_mistaken_for_pii():
    records, manifest = curated()
    ok = (records[0].model_copy(update={"messages": ({"role": "user", "content": "10,000-yard race, size 12, under $100, 190 lbs"},
                                                      *records[0].messages[1:])}),)
    assert build_dataset(ok, rebuilt(ok, manifest)).record_count == 1


def test_non_card_numeric_catalog_ids_are_not_mistaken_for_pii():
    records, manifest = curated()
    ok = (records[0].model_copy(update={"messages": ({"role": "user", "content": "catalog id amazon2023:1234567890123"},
                                                      *records[0].messages[1:])}),)
    assert build_dataset(ok, rebuilt(ok, manifest)).record_count == 1
