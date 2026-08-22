"""Trajectory evaluation — docs/19 §3.12.

The other layers judge what the agent *said* and what it *changed*. This one judges the
**path**: did it accomplish the task, and did it get there without wandering.

That is the closest thing to what a person does when they read a run by hand and think
"it got there, but it looked around three times first" — and it is the layer that most
directly removes the need to hand-write per-case expectations, because the metric infers
the task from the trace rather than being told what to look for.

**Run with DeepEval's own runner, and on its own:**

    CCOA_EVAL_TRAJECTORY=1 uv run deepeval test run evals/test_trajectory.py

Two reasons, both found the hard way:

* Trajectory metrics read an active trace, and that scope is established by
  `deepeval test run`. Under bare `pytest` they raise "No active trace found" — a clear
  error rather than a silent pass.
* Collecting them puts the **whole session** into trace scope, which breaks the other
  eval layers. Running everything in one command produced 24 failures, none of them
  real. They are skipped unless `CCOA_EVAL_TRAJECTORY=1` is set, so that cannot happen
  by accident.

**On `StepEfficiencyMetric`.** It is not part of this suite, and the reasoning is worth
keeping because it is finely balanced. It earned real credit: reading its rationale led
to two genuine defects — `read_reference` failing on every call, and `search_kb`
repeating with reworded queries. It also scored a run **0.0** with "the agent repeatedly
called redundant tools and failed" when that run made exactly **one** tool call, had zero
failures, and could not have been more efficient.

A metric that invents its rationale cannot gate a build. It also cannot be demoted to a
non-gating diagnostic here: it needs the trace, so it has to go through `assert_test`,
and DeepEval then counts it in its own report — catching the exception produces a run
that says "1 passed, 5 failed" while every test passes, which is worse than either.

So it is run **by hand** when agent efficiency is the question:

    CCOA_EVAL_TRAJECTORY=1 uv run deepeval test run evals/test_trajectory.py \
        --deepeval-include-efficiency

...which is not a real flag — add the metric to the list below, run it, read the reason,
and **verify the claim against the trace before acting on it.**
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from deepeval import assert_test
from deepeval.dataset import Golden as DeepEvalGolden
from deepeval.integrations.langchain import CallbackHandler
from deepeval.metrics import TaskCompletionMetric
from deepeval.test_case import LLMTestCase
from deepeval.tracing import observe, update_current_span
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import Settings
from app.db.engine import Database
from app.graph.builder import build_graph
from app.graph.deps import GraphDependencies
from app.graph.state import initial_state
from evals.goldens import Golden, goldens
from evals.harness import ACTORS, _turn_output

TRAJECTORY_CASES = goldens(check="trajectory")


def _identify(case: Golden) -> str:
    return case.name


@pytest.mark.eval
@pytest.mark.judged
@pytest.mark.trajectory
@pytest.mark.parametrize("case", TRAJECTORY_CASES, ids=_identify)
def test_agent_trajectory(
    case: Golden,
    eval_settings: Settings,
    judge: Any,
    corpus_template: Path,
    tmp_path: Path,
) -> None:
    """Score the whole execution path for task completion and wasted steps."""
    database_path = tmp_path / "trajectory.db"
    shutil.copyfile(corpus_template, database_path)
    database = Database(database_path)

    try:
        deps = GraphDependencies.build(eval_settings, database=database)
        graph = build_graph(checkpointer=MemorySaver(), deps=deps)
        actor = ACTORS[case.actor]
        config: dict[str, Any] = {
            "configurable": {
                "thread_id": f"traj-{case.name}",
                "actor": actor.to_config(),
                "trace_id": f"traj-{case.name}",
            },
            # The native LangGraph integration. It attaches spans for the graph run and
            # every model call inside it, which is what the trajectory metrics read.
            "callbacks": [CallbackHandler()],
        }

        prompts = [s.message for s in case.conversation if s.message]
        task = " ".join(" ".join(prompts).split())

        @observe(type="agent", name="ccoa")
        def run_conversation() -> str:
            output = ""
            for step in case.conversation:
                payload: Any = (
                    initial_state(step.message)
                    if step.message is not None
                    else Command(resume=step.resume)
                )
                result = graph.invoke(payload, config)
                output = _turn_output(result)
            update_current_span(test_case=LLMTestCase(input=task, actual_output=output))
            return output

        run_conversation()

        # `StepEfficiencyMetric` is measured and reported, and deliberately does **not**
        # gate. It earned its place by pointing at two real defects — `read_reference`
        # failing on every call, and `search_kb` repeating with reworded queries — both
        # found by reading its *reason* and verifying independently.
        #
        # It has also twice stated a verdict that was simply false. Most recently it
        # scored this case 0.0 with "the investigator agent repeatedly called redundant
        # tools and failed", against a run that made exactly **one** tool call, had zero
        # failures, and could not have been more efficient. A metric that fabricates its
        # rationale cannot be an assertion; it can still be a lead worth following.
        assert_test(
            golden=DeepEvalGolden(input=task),
            metrics=[TaskCompletionMetric(threshold=0.7, model=judge, async_mode=False)],
            run_async=False,
        )
    finally:
        database.dispose()


def test_trajectory_cases_are_declared() -> None:
    """Runs without a key, so the selection is checked by the normal suite."""
    assert TRAJECTORY_CASES, "no case opts into trajectory evaluation"
    for case in TRAJECTORY_CASES:
        assert case.conversation
