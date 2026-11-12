"""Static GPU readiness: Modal image pins match docs/model-runs/GPU_READINESS.md; the smoke ceiling clears the gate."""
import re
from decimal import Decimal
from pathlib import Path

from training.gates import affordable_seconds, list_rates

DOC = Path("docs/model-runs/GPU_READINESS.md").read_text()
PIN = re.compile(r'"([A-Za-z0-9_.-]+==[0-9][^"]*)"')


def documented(block: str) -> list[str]:
    return sorted(re.search(rf"```{block}\n(.*?)```", DOC, re.S).group(1).split())


def test_inference_image_pins_match_the_documented_pins():
    src = Path("modal_app/qwen_inference.py").read_text()
    assert sorted(PIN.findall(src[src.index(".pip_install("):src.index(".add_local_python_source")])) == documented("pins-inference")


def test_concurrent_inference_generate_is_published_as_a_modal_method():
    src = Path("modal_app/qwen_inference.py").read_text()
    assert "@modal.method()\n    async def generate" in src


def test_training_image_pins_match_the_documented_pins():
    src = Path("modal_app/qwen_training.py").read_text()
    assert sorted(PIN.findall(src[src.index("TRAIN_PINS = ("):src.index("def _download_model")])) == documented("pins-training")


def test_smoke_ceiling_buys_the_documented_seconds_and_clears_the_60s_gate():
    assert affordable_seconds(Decimal("0.20"), list_rates()) == 626 >= 60 and "626 s" in DOC
