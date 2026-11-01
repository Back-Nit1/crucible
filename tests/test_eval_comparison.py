import json

import pytest

from eval.artifacts import write_comparison
from eval.comparison import ContenderRun, compare_contenders
from tests.test_training_curation import successful_episode


def measured_run(contender_id, checkpoint, memory, latency):
    task, episode = successful_episode(f"{contender_id}-1")
    one = episode.model_copy(update={
        "seed": 1,
        "model_metadata": ({"latency_ms": latency, "model": contender_id},),
    })
    two = episode.model_copy(update={
        "episode_id": f"{contender_id}-2",
        "seed": 2,
        "model_metadata": ({"latency_ms": latency + 10, "model": contender_id},),
    })
    return task, ContenderRun(
        contender_id=contender_id,
        checkpoint=checkpoint,
        memory_enabled=memory,
        episodes=(one, two),
    )


def test_comparison_requires_identical_tasks_and_seeds_and_exports_reports(tmp_path):
    task, base = measured_run("base", "qwen-base", False, 20)
    _, memory = measured_run("memory", "qwen-base", True, 25)
    report = compare_contenders((base, memory), {task.id: task}, pass_k=2)
    assert report.task_seed_pairs == ((task.id, 1), (task.id, 2))
    assert report.contenders[0].evaluation.metrics["success_rate"].value == 1
    assert report.contenders[0].evaluation.metrics["latency_ms"].value == 25
    json_path, markdown_path = write_comparison(report, tmp_path, "held-out")
    assert json.loads(json_path.read_text())["pass_k"] == 2
    assert "| base | qwen-base | off |" in markdown_path.read_text()


def test_comparison_rejects_mismatched_seed_sets_and_unknown_tasks():
    task, base = measured_run("base", "qwen-base", False, 20)
    _, memory = measured_run("memory", "qwen-base", True, 20)
    mismatched = memory.model_copy(update={"episodes": memory.episodes[:1]})
    with pytest.raises(ValueError, match="identical"):
        compare_contenders((base, mismatched), {task.id: task}, pass_k=1)
    unknown_episode = base.episodes[0].model_copy(update={"task_id": "unknown"})
    unknown = base.model_copy(update={"episodes": (unknown_episode,)})
    with pytest.raises(ValueError, match="unknown tasks"):
        compare_contenders((unknown,), {task.id: task}, pass_k=1)
