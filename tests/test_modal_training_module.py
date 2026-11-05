"""Importing the Modal training module must be free: no network, no GPU, no resources created."""
import importlib



def load(monkeypatch, enabled):
    if enabled:
        monkeypatch.setenv("CRUCIBLE_ENABLE_L4_TRAIN", "1")
    else:
        monkeypatch.delenv("CRUCIBLE_ENABLE_L4_TRAIN", raising=False)
    import modal_app.qwen_training as mod
    return importlib.reload(mod)


def test_gpu_is_attached_only_when_explicitly_enabled(monkeypatch):
    assert load(monkeypatch, False).ENABLED is False
    assert load(monkeypatch, True).ENABLED is True
    load(monkeypatch, False)


def test_pins_are_exact_and_cover_the_training_stack(monkeypatch):
    mod = load(monkeypatch, False)
    assert all("==" in pin for pin in mod.TRAIN_PINS)
    names = {pin.split("==")[0] for pin in mod.TRAIN_PINS}
    assert {"torch", "transformers", "peft", "bitsandbytes", "accelerate", "safetensors"} <= names


def test_inference_and_training_share_overlapping_pins(monkeypatch):
    mod = load(monkeypatch, False)
    import inspect
    import modal_app.qwen_inference as inference
    source = inspect.getsource(inference)
    for pin in mod.TRAIN_PINS:
        if pin.split("==")[0] in {"torch", "transformers", "accelerate", "safetensors", "huggingface-hub"}:
            assert f'"{pin}"' in source, pin


def test_timeout_is_under_the_approved_forty_five_minutes_and_above_the_soft_stop(monkeypatch):
    from training.gates import MAX_LAUNCH_SECONDS
    mod = load(monkeypatch, False)
    assert MAX_LAUNCH_SECONDS < mod.TIMEOUT_SECONDS <= 45 * 60


def test_each_algorithm_is_enabled_by_its_own_deploy_flag(monkeypatch):
    monkeypatch.delenv("CRUCIBLE_ENABLE_L4_TRAIN", raising=False)
    monkeypatch.delenv("CRUCIBLE_ENABLE_L4_RL", raising=False)
    import modal_app.qwen_training as mod
    mod = importlib.reload(mod)
    assert (mod.ENABLED, mod.ALGORITHMS) == (False, "")  # fail closed: no GPU, no algorithm
    monkeypatch.setenv("CRUCIBLE_ENABLE_L4_RL", "1")
    mod = importlib.reload(mod)
    assert (mod.ENABLED, mod.ALGORITHMS) == (True, "grpo")  # RL alone does not enable SFT
    monkeypatch.setenv("CRUCIBLE_ENABLE_L4_TRAIN", "1")
    assert importlib.reload(mod).ALGORITHMS == "sft,grpo"
    monkeypatch.delenv("CRUCIBLE_ENABLE_L4_RL")
    monkeypatch.delenv("CRUCIBLE_ENABLE_L4_TRAIN")
    importlib.reload(mod)
    assert repr(mod.train) == "Function(train)"  # registers offline, never deployed
