"""Loading and validating the eval dataset — docs/19 §3.3.

The dataset is YAML so that an expectation about agent behaviour reads as prose in a
diff. It is validated with the same strictness as a skill file: unknown keys are an
error, because a mistyped expectation would otherwise silently assert nothing and the
eval would pass for the wrong reason.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DATASET_PATH = Path(__file__).parent / "dataset.yaml"

InterruptKind = Literal["clarify", "confirm", "approve", "steer", "none"]
WriteKind = Literal["none", "ticket", "escalation"]
ActorKind = Literal["agent", "supervisor"]

#: Which judged layers a case opts into. Each costs judge calls, so it is stated per
#: case rather than applied to everything — the bill should be visible in the dataset.
Check = Literal["conversational", "safety", "trajectory"]

#: What the assistant is supposed to be. `RoleAdherenceMetric` scores against this, and
#: `RoleViolationMetric` uses it to decide what counts as stepping outside the role.
CHATBOT_ROLE = (
    "An operations assistant for an insurance contact centre, helping a support agent "
    "look up customers, review past contacts, investigate claim problems, and draft "
    "tickets. It answers only from retrieved records and asks the agent when a choice "
    "is genuinely ambiguous."
)


class Rubric(BaseModel):
    """An LLM-judged quality bar.

    Deliberately optional per case: a judge call costs money and introduces variance,
    so it is spent only where a deterministic check cannot express what matters.
    """

    model_config = ConfigDict(extra="forbid")

    criteria: str = Field(min_length=20)
    steps: list[str] = Field(default_factory=list)
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class Expectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    interrupt_kind: InterruptKind = "none"
    interrupt_contains: list[str] = Field(default_factory=list)
    must_cite: list[str] = Field(default_factory=list)
    must_mention: list[str] = Field(default_factory=list)
    must_not_mention: list[str] = Field(default_factory=list)
    grounded: bool = False
    writes: WriteKind = "none"
    min_model_calls: int | None = None
    max_model_calls: int | None = None


class Step(BaseModel):
    """One turn: either the human says something, or resumes a checkpoint."""

    model_config = ConfigDict(extra="forbid")

    message: str | None = None
    resume: dict[str, object] | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Step:
        if bool(self.message) == bool(self.resume):
            raise ValueError("a step must carry exactly one of `message` or `resume`")
        return self


class Golden(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = Field(min_length=20)
    conversation: list[Step] = Field(min_length=1)
    expect: Expectation
    #: Which Cognito groups the caller holds. `supervisor` implies `agent`.
    actor: ActorKind = "supervisor"
    rubric: Rubric | None = None

    #: Judged layers beyond the rubric. Opt-in, because each one costs.
    checks: list[Check] = Field(default_factory=list)
    #: Context for the conversational metrics. `scenario` frames what the human was
    #: trying to do; `expected_outcome` is what a good conversation ends with.
    scenario: str | None = None
    expected_outcome: str | None = None

    @property
    def judged(self) -> bool:
        return self.rubric is not None

    def wants(self, check: Check) -> bool:
        return check in self.checks

    @model_validator(mode="after")
    def _conversational_checks_need_context(self) -> Golden:
        if "conversational" in self.checks and not self.expected_outcome:
            raise ValueError(
                f"{self.name}: a conversational check needs `expected_outcome`, or the "
                f"metric has nothing to judge completeness against"
            )
        return self


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[Golden] = Field(min_length=1)

    @model_validator(mode="after")
    def _names_are_unique(self) -> Dataset:
        names = [case.name for case in self.cases]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"duplicate case names: {sorted(duplicates)}")
        return self


def load_dataset(path: Path | None = None) -> Dataset:
    source = path or DATASET_PATH
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    return Dataset.model_validate(raw)


def goldens(*, judged_only: bool = False, check: Check | None = None) -> list[Golden]:
    cases = load_dataset().cases
    if check is not None:
        return [c for c in cases if c.wants(check)]
    return [c for c in cases if c.judged] if judged_only else cases


def by_name(name: str) -> Golden:
    for case in load_dataset().cases:
        if case.name == name:
            return case
    raise KeyError(f"no eval case named {name!r}")
