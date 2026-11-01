"""Real PyTorch/PEFT backend on a tiny randomly-initialised Qwen2 (CPU). Skipped unless torch+transformers+peft are
installed AND a local copy of the pinned Qwen tokenizer is pointed to by CRUCIBLE_TEST_QWEN_TOKENIZER_DIR; run with:

  CRUCIBLE_TEST_QWEN_TOKENIZER_DIR=<dir with tokenizer.json,...> uv run --no-project --with-requirements ... pytest ...
(see docs/handoffs/modal-training-runtime.md for the exact command)."""
import datetime as dt
import os
from decimal import Decimal
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("peft")
transformers = pytest.importorskip("transformers")
TOK = os.environ.get("CRUCIBLE_TEST_QWEN_TOKENIZER_DIR")
pytestmark = pytest.mark.skipif(not TOK or not Path(TOK, "tokenizer.json").exists(), reason="no local Qwen tokenizer")

from modal_app.adapter_artifact import verify_adapter_dir  # noqa: E402
from tests.test_training_dataset import curated, rebuilt  # noqa: E402
from training.dataset import build_dataset  # noqa: E402
from training.planning import LoRAHyperparameters, plan_hash, build_lora_plan  # noqa: E402
from training.resume import CheckpointStore, RunIdentity  # noqa: E402
from training.shard import parse_shard  # noqa: E402
from training.torch_backend import IGNORE_INDEX, TorchLoraBackend, backend_signature, encode_example, load_base_model  # noqa: E402
from training.trainer import run_training  # noqa: E402

NOW = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
HP = LoRAHyperparameters(method="lora_sft", quantization="none", epochs=2, lora_rank=4, lora_alpha=8, lora_dropout=Decimal("0.1"),
                         learning_rate=Decimal("0.01"), micro_batch_size=1, gradient_accumulation_steps=2, warmup_steps=1,
                         checkpoint_every_steps=1, target_modules=("q_proj", "v_proj"), max_sequence_length=4096, seed=3)


@pytest.fixture(scope="module")
def tiny_model_dir(tmp_path_factory):
    path = tmp_path_factory.mktemp("tiny")
    tok = transformers.AutoTokenizer.from_pretrained(TOK)
    torch.manual_seed(0)
    config = transformers.Qwen2Config(vocab_size=len(tok), hidden_size=32, intermediate_size=64, num_hidden_layers=2,
                                      num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=4096,
                                      tie_word_embeddings=True)
    transformers.Qwen2ForCausalLM(config).save_pretrained(path)
    tok.save_pretrained(path)
    return str(path)


def shard():
    records, manifest = curated()
    many = tuple(records[0].model_copy(update={
        "source_episode_id": f"ep-{i}", "messages": ({"role": "user", "content": f"need running shoes variant {i}, under $100"},
                                                     *records[0].messages[1:])}) for i in range(3))
    manifest = rebuilt(many, manifest)
    data = build_dataset(many, manifest)
    return parse_shard(data.shard, expected_dataset_hash=data.dataset_hash, expected_manifest_hash=manifest.content_hash), data, manifest


def test_labels_cover_only_assistant_tool_call_turns(tiny_model_dir):
    sh, _, _ = shard()
    tok = transformers.AutoTokenizer.from_pretrained(tiny_model_dir)
    ids, labels = encode_example(tok, sh.system, sh.tools, sh.examples[0], 4096)
    trained = tok.decode([t for t in labels if t != IGNORE_INDEX])
    assert trained.count("<tool_call>") == trained.count("</tool_call>") >= 6 and trained.rstrip().endswith("<|im_end|>")
    assert "<tool_response>" not in trained and "need running shoes" not in trained and "careful shopping agent" not in trained
    assert len(ids) == len(labels)


def run(tmp_path, model_dir, sh, data, manifest, stop=None):
    model, tok = load_base_model(model_dir, HP, device="cpu", require_cuda_for_large=False)
    steps = HP.total_steps(sh.examples.__len__())
    backend = TorchLoraBackend(model=model, tokenizer=tok, shard=sh, hp=HP, total_steps=steps, device="cpu")
    plan = build_lora_plan(manifest, base_model="tiny/qwen2", base_revision="a" * 40, gpu="L4",
                           maximum_approved_cost=Decimal("1"), hyperparameters=HP)
    identity = RunIdentity(run_id="run-tiny", plan_hash=plan_hash(plan), base_model="tiny/qwen2", base_revision="a" * 40,
                           training_manifest_hash=manifest.content_hash, dataset_hash=data.dataset_hash,
                           hyperparameters=HP.model_dump(mode="json"), backend_signature=backend_signature())
    store = CheckpointStore(tmp_path, identity, clock=lambda: NOW)
    return run_training(store=store, identity=identity, backend=backend, hp=HP, record_count=len(sh.examples),
                        total_budget_seconds=600, gpu="cpu-test", clock=lambda: NOW, stop_after_steps=stop), store


def test_real_training_resume_equals_uninterrupted_run(tiny_model_dir, tmp_path):
    sh, data, manifest = shard()
    whole, store_whole = run(tmp_path / "whole", tiny_model_dir, sh, data, manifest)
    assert whole.status == "final" and whole.step == whole.total_steps == 4
    assert whole.losses[-1] < whole.losses[0]  # it actually learns on a toy overfit
    first, _ = run(tmp_path / "split", tiny_model_dir, sh, data, manifest, stop=2)
    assert first.status == "paused" and first.manifest is None
    second, store_split = run(tmp_path / "split", tiny_model_dir, sh, data, manifest)  # fresh model + optimizer objects
    assert second.status == "final" and second.resumed_from_step == 2
    assert second.manifest.adapter_hash == whole.manifest.adapter_hash  # bit-identical adapter => optimizer/sched/RNG restored
    verify_adapter_dir(second.manifest, store_split.final_dir)


def test_adapter_artifact_is_adapter_only(tiny_model_dir, tmp_path):
    sh, data, manifest = shard()
    out, store = run(tmp_path, tiny_model_dir, sh, data, manifest)
    names = {f.path for f in out.manifest.adapter_files}
    assert names == {"adapter_config.json", "adapter_model.safetensors"}
    from safetensors.torch import load_file
    keys = load_file(str(store.final_dir / "adapter_model.safetensors")).keys()
    assert keys and all("lora_" in k for k in keys)


def test_cpu_refused_for_quantized_or_large_models(tiny_model_dir):
    from training.torch_backend import BackendError
    with pytest.raises(BackendError) as err:
        load_base_model(tiny_model_dir, LoRAHyperparameters(), device="cpu")
    assert err.value.code == "cpu_refused"
