"""The agent evaluation suite — docs/19.

Every case in `dataset.yaml` runs twice over:

* once against **deterministic** metrics, which are the bulk of what matters and cost
  nothing;
* and, where the case carries a rubric, once against an **LLM judge**.

They are separate pytest cases on purpose. When an eval fails you want to know
immediately whether the agent did the wrong *thing* or merely said it badly — those
have completely different fixes, and a single combined pass/fail hides which it was.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from deepeval import assert_test

from app.config import Settings
from evals.goldens import Golden, goldens
from evals.harness import Trace, run_case
from evals.metrics import (
    argument_metric,
    conversational_metrics,
    deterministic_metrics,
    disclosure_metric,
    judge_metric,
    safety_metrics,
    to_conversational_test_case,
    to_test_case,
    wants_argument_check,
)

ALL_CASES = goldens()
JUDGED_CASES = goldens(judged_only=True)
CONVERSATIONAL_CASES = goldens(check="conversational")
SAFETY_CASES = goldens(check="safety")


def _identify(case: Golden) -> str:
    return case.name


@pytest.fixture(scope="module")
def traces() -> dict[str, Trace]:
    """Cache each case's trace for the module.

    A judged case and its deterministic counterpart evaluate the *same* run. Running
    the conversation twice would double the cost and, worse, let the two halves
    disagree about what the agent actually did.
    """
    return {}


def _trace_for(
    case: Golden,
    traces: dict[str, Trace],
    settings: Settings,
    db_path: Path,
    factory: Any,
) -> Trace:
    if case.name not in traces:
        traces[case.name] = run_case(
            case, settings=settings, db_path=db_path, model_factory=factory
        )
    return traces[case.name]


@pytest.mark.eval
@pytest.mark.parametrize("case", ALL_CASES, ids=_identify)
def test_agent_behaviour(
    case: Golden,
    traces: dict[str, Trace],
    eval_settings: Settings,
    case_db: Path,
    model_factory: Any,
) -> None:
    """Facts: which tools ran, what was written, what the answer is allowed to assert."""
    trace = _trace_for(case, traces, eval_settings, case_db, model_factory)
    print(f"\n{trace.summary()}")

    assert_test(
        test_case=to_test_case(case, trace),
        metrics=deterministic_metrics(case, trace),
        run_async=False,
    )


@pytest.mark.eval
@pytest.mark.judged
@pytest.mark.parametrize("case", JUDGED_CASES, ids=_identify)
def test_agent_quality(
    case: Golden,
    traces: dict[str, Trace],
    eval_settings: Settings,
    case_db: Path,
    model_factory: Any,
    judge: Any,
) -> None:
    """Judgement: is the answer any good, against the case's rubric."""
    assert case.rubric is not None
    trace = _trace_for(case, traces, eval_settings, case_db, model_factory)

    assert_test(
        test_case=to_test_case(case, trace),
        metrics=[judge_metric(case.rubric, judge)],
        run_async=False,
    )


@pytest.mark.eval
@pytest.mark.judged
@pytest.mark.parametrize("case", CONVERSATIONAL_CASES, ids=_identify)
def test_agent_conversation(
    case: Golden,
    traces: dict[str, Trace],
    eval_settings: Settings,
    case_db: Path,
    model_factory: Any,
    judge: Any,
) -> None:
    """Multi-turn behaviour: does it remember, stay in role, and finish the job?

    Scored over the whole conversation rather than the last answer. A single-turn view
    cannot see that the assistant forgot which customer it was told about two turns ago,
    which is the failure mode this layer exists for.
    """
    trace = _trace_for(case, traces, eval_settings, case_db, model_factory)
    assert_test(
        test_case=to_conversational_test_case(case, trace),
        metrics=conversational_metrics(judge),
        run_async=False,
    )


@pytest.mark.eval
@pytest.mark.judged
@pytest.mark.parametrize("case", SAFETY_CASES, ids=_identify)
def test_agent_safety(
    case: Golden,
    traces: dict[str, Trace],
    eval_settings: Settings,
    case_db: Path,
    model_factory: Any,
    judge: Any,
) -> None:
    """What the answer discloses, and whether the tools were called sensibly."""
    trace = _trace_for(case, traces, eval_settings, case_db, model_factory)
    test_case = to_test_case(case, trace)

    metrics = [*safety_metrics(judge), disclosure_metric(judge)]
    if trace.tools_called and wants_argument_check(case):
        metrics.append(argument_metric(judge))

    assert_test(test_case=test_case, metrics=metrics, run_async=False)


def test_the_dataset_is_valid() -> None:
    """Runs without a key, so a malformed dataset is caught by the normal suite.

    An eval suite that only validates itself when someone has credentials is an eval
    suite that breaks silently.
    """
    assert len(ALL_CASES) >= 10
    assert JUDGED_CASES, "at least one case should carry a rubric"
    assert CONVERSATIONAL_CASES, "at least one case should be judged conversationally"
    assert SAFETY_CASES, "at least one case should be checked for disclosure"

    for case in ALL_CASES:
        assert case.conversation, f"{case.name} has no conversation"
        if case.expect.interrupt_contains:
            assert case.expect.interrupt_kind != "none", (
                f"{case.name} expects no checkpoint but asserts its contents"
            )
        # A case that asserts a write must say which kind, or it asserts nothing.
        for ref in case.expect.must_cite:
            assert ":" in ref, f"{case.name}: {ref!r} is not an evidence ref"
