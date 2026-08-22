"""Tool descriptions, loaded from ``app/agents/tools.yaml``.

Descriptions are prompt text: the model reads them to decide what to call. Keeping them
out of Python is the same rule as system prompts (docs/17 §3.9), and it is enforced
symmetrically — a registered tool with no entry fails boot, and an entry with no tool
fails boot too, so the file cannot quietly accumulate descriptions for tools that no
longer exist.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

DESCRIPTIONS_PATH = Path(__file__).resolve().parents[2] / "agents" / "tools.yaml"


class ToolDescription(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=8, max_length=160)
    description: str = Field(min_length=20, max_length=1200)


class DescriptionError(RuntimeError):
    """The description asset is missing, malformed, or out of step with the registry."""


@lru_cache(maxsize=1)
def load_descriptions(path: Path | None = None) -> dict[str, ToolDescription]:
    source = path or DESCRIPTIONS_PATH
    if not source.is_file():
        raise DescriptionError(f"tool descriptions not found: {source}")

    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise DescriptionError(f"{source}: expected a mapping of tool name to description")

    loaded: dict[str, ToolDescription] = {}
    for name, entry in raw.items():
        try:
            loaded[str(name)] = ToolDescription.model_validate(entry)
        except Exception as exc:
            raise DescriptionError(f"{source}: invalid entry for {name!r} — {exc}") from exc
    return loaded


def describe(name: str) -> str:
    """The model-facing description for one tool."""
    try:
        return " ".join(load_descriptions()[name].description.split())
    except KeyError:
        raise DescriptionError(f"tool {name!r} has no entry in {DESCRIPTIONS_PATH.name}") from None


def assert_in_step(registered: frozenset[str]) -> None:
    """Fail boot if descriptions and the tool registry have drifted apart."""
    described = frozenset(load_descriptions())
    if missing := sorted(registered - described):
        raise DescriptionError(f"tools with no description: {missing}")
    if orphaned := sorted(described - registered):
        raise DescriptionError(f"descriptions for tools that do not exist: {orphaned}")
