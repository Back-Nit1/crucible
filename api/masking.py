"""DEMO_MODE=1 brand masking: judges see products, not third-party brand names. Text only; this codebase has no logo or image fields.
Hides the structured `brand` and its occurrences in titles/review text. Brands that appear only in free text with no
`brand` field (e.g. a model name in a review) are NOT detected: masking is best-effort and documented as such."""
import os
import re

from catalog.providers.base import Product

HIDDEN = "[brand hidden]"
_BRANDISH = re.compile(r"brand|manufacturer|maker", re.I)


def demo_mode() -> bool:
    return os.environ.get("DEMO_MODE") == "1"


def hide(text: str | None, brand: str | None) -> str | None:
    """Replace every case-insensitive occurrence of `brand` in `text` (no-op without demo mode or brand)."""
    if not (demo_mode() and text and brand and brand.strip()):
        return text
    return re.sub(re.escape(brand.strip()), HIDDEN, text, flags=re.I)


def mask_product(p: Product | None) -> Product | None:
    if p is None or not demo_mode():
        return p
    attrs = {k: v for k, v in p.attributes.items() if not _BRANDISH.search(str(k))}
    return p.model_copy(update={"title": hide(p.title, p.brand), "brand": None, "attributes": attrs})
