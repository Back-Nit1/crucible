"""Configuration placeholders only; no model claims or external calls."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Contender:
    id: str
    model_checkpoint: str
    memory_enabled: bool
    optional: bool = False


CONTENDERS = (
    Contender("base-qwen", "qwen-base-placeholder", False),
    Contender("base-qwen-memory", "qwen-base-placeholder", True),
    Contender("survivor-finetuned-memory", "survivor-checkpoint-placeholder", True),
    Contender("frontier-ceiling", "frontier-placeholder", False, optional=True),
)


class WebShopAdapter(Protocol):
    def run(self, contender: Contender, seed: int) -> object: ...


class WebShopNotConfigured:
    def run(self, contender: Contender, seed: int) -> object:
        raise NotImplementedError("WebShop integration is a protocol stub; dataset adapter remains")
