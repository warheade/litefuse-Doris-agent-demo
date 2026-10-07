"""Environment loading and per-model pricing."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# The Langfuse SDK reads LANGFUSE_HOST / LANGFUSE_BASE_URL; accept either.
os.environ.setdefault("LANGFUSE_BASE_URL", os.getenv("LANGFUSE_HOST", "http://localhost:3000"))
os.environ.setdefault("LANGFUSE_HOST", os.environ["LANGFUSE_BASE_URL"])


def _patch_sdk_for_litefuse() -> None:
    """Langfuse SDK >= 4.11 requires `mediaReferences` on dataset items, but the
    Litefuse 26.2.0 server does not return it, so every dataset call fails to parse.
    Default the field to [] (the SDK already treats an empty list as "no media")."""
    from langfuse.api.commons.types.dataset_item import DatasetItem
    from langfuse.api.dataset_items.types.paginated_dataset_items import PaginatedDatasetItems

    field = DatasetItem.model_fields.get("media_references")
    if field is not None and field.is_required():
        field.default_factory = list
        DatasetItem.model_rebuild(force=True)
        PaginatedDatasetItems.model_rebuild(force=True)


_patch_sdk_for_litefuse()

PROMPT_NAME = "support-system"
DATASET_NAME = "support-golden"

# USD per 1M tokens (input, output). Sent as cost_details so Litefuse shows cost
# even for models missing from its built-in price table.
CLAUDE_PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def tool_fail_rate() -> float:
    return float(env("TOOL_FAIL_RATE", "0") or 0)


def price_for(provider: str, model: str) -> tuple[float, float] | None:
    if provider == "claude":
        return CLAUDE_PRICES.get(model)
    pin, pout = env("OPENAI_PRICE_INPUT_PER_MTOK"), env("OPENAI_PRICE_OUTPUT_PER_MTOK")
    if pin and pout:
        return float(pin), float(pout)
    return None
