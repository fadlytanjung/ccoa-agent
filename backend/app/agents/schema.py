"""Skill frontmatter schema — docs/17 §3.4.

Validated at boot. Unknown keys are an **error**, not a warning: a typo in a key name
would otherwise silently disable the setting it was meant to change, and the failure
would show up as strange model behaviour weeks later rather than as a failed deploy.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AskKind = Literal["clarify", "confirm", "approve", "steer"]

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_SLUG = re.compile(r"^[a-z][a-z0-9_]*$")


class SkillLimits(BaseModel):
    """Loop bounds for agentic skills — docs/05 §3.5.

    Enforced by the graph, not requested of the model. A model asked to "stop after six
    tool calls" will sometimes not.
    """

    model_config = ConfigDict(extra="forbid")

    max_iterations: int = Field(default=6, ge=1, le=20)
    max_parallel_tools: int = Field(default=3, ge=1, le=10)
    wall_clock_seconds: int = Field(default=45, ge=5, le=300)


class HumanCheckpoint(BaseModel):
    """A declared human-in-the-loop trigger.

    ``approve`` is enforced in code; the rest are advisory and read as policy by the
    orchestrator. Over-enforcing `clarify` and `confirm` is what turns a conversation
    into an interrogation (docs/05 §3.7).
    """

    model_config = ConfigDict(extra="forbid")

    kind: AskKind
    when: str = Field(min_length=4, max_length=300)


class SkillFrontmatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    #: What the orchestrator sees. This is the delegation menu (docs/17 §3.5), so it is
    #: written as guidance about *when to delegate here*, not as a summary of the skill.
    description: str = Field(min_length=20, max_length=400)

    model: str | None = None
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    max_output_tokens: int = Field(default=2048, ge=128, le=8192)

    tools: tuple[str, ...] = ()
    limits: SkillLimits = Field(default_factory=SkillLimits)
    human_checkpoints: tuple[HumanCheckpoint, ...] = ()
    requires_groups: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    templates: tuple[str, ...] = ()

    @field_validator("name")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not _SLUG.match(value):
            raise ValueError(f"name must be a lowercase slug, got {value!r}")
        return value

    @field_validator("version")
    @classmethod
    def _semver(cls, value: str) -> str:
        if not _SEMVER.match(value):
            raise ValueError(f"version must be semver (e.g. 1.2.0), got {value!r}")
        return value

    @field_validator("references", "templates")
    @classmethod
    def _relative_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for path in value:
            if path.startswith("/") or ".." in path.split("/"):
                raise ValueError(f"path must stay inside the skill directory, got {path!r}")
        return value


class SkillDescriptor(BaseModel):
    """Tier 1 — what the orchestrator loads for every skill, always."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    description: str


class Skill(BaseModel):
    """Tier 2 — the full skill, loaded when its specialist actually runs."""

    model_config = ConfigDict(frozen=True)

    frontmatter: SkillFrontmatter
    #: The Markdown body, verbatim. This *is* the system prompt.
    body: str
    #: SHA-256 over the skill directory, logged at boot so an output regression can be
    #: attributed to a specific prompt version.
    digest: str

    @property
    def name(self) -> str:
        return self.frontmatter.name

    @property
    def version(self) -> str:
        return self.frontmatter.version

    @property
    def tools(self) -> tuple[str, ...]:
        return self.frontmatter.tools

    def descriptor(self) -> SkillDescriptor:
        return SkillDescriptor(
            name=self.frontmatter.name,
            version=self.frontmatter.version,
            description=self.frontmatter.description.strip(),
        )

    def checkpoint_for(self, kind: AskKind) -> HumanCheckpoint | None:
        for checkpoint in self.frontmatter.human_checkpoints:
            if checkpoint.kind == kind:
                return checkpoint
        return None
