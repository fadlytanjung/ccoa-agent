"""Eval fixtures — docs/19 §3.2.

Evals need what tests deliberately refuse: a real model, a real key, and the network.
They are therefore a separate suite with a separate entry point, and they skip rather
than fail when no key is configured — a contributor without one should still be able to
run everything else.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from langchain_core.language_models import BaseChatModel

from app.config import Settings
from app.db.engine import Database
from app.seed import generate, write
from app.services.llm import build_model_factory

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# DeepEval ships telemetry that posts usage events to a third party on every run. This
# project keeps third-party egress opt-in and says so (docs/10 §6); an eval suite that
# quietly contradicts that is worse than one that never mentions it. Set before any
# deepeval import so it takes effect on module load.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("ERROR_REPORTING", "NO")


#: Opt-in flag for the trajectory layer. See `pytest_collection_modifyitems`.
TRAJECTORY_FLAG = "CCOA_EVAL_TRAJECTORY"

#: The model the *agent under test* runs on during evals, and the model that *judges*.
#:
#: The agent runs on **the shipped model**, so a passing eval is evidence about what
#: actually deploys. An earlier version defaulted this to `gemini-2.5-flash` to dodge
#: quota pressure; that was abandoned once it turned out `gemini-2.5-flash` is being
#: withdrawn for newly-created projects and returns, intermittently:
#:
#:     404 — This model models/gemini-2.5-flash is no longer available to new users.
#:
#: Intermittently is the problem. It answered a direct call and 404'd the preflight
#: seconds later, which is the worst possible property in a model you evaluate against.
#:
#: The **judge** is a different question and does not have to match: it scores, it is
#: not the system under test, and it is called dozens of times per pass. `-lite` there
#: is a straight saving. Override either when investigating.
EVAL_MODEL = os.environ.get("CCOA_EVAL_MODEL", "gemini-3.5-flash")
EVAL_JUDGE_MODEL = os.environ.get("CCOA_EVAL_JUDGE_MODEL", "gemini-3.5-flash-lite")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "eval: an agent evaluation — needs a real model key")
    config.addinivalue_line("markers", "judged: uses an LLM judge, so it costs a call")
    config.addinivalue_line("markers", "trajectory: scores the agent's whole execution path")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Keep the trajectory layer out of ordinary eval sessions.

    Trajectory metrics need an active DeepEval trace, and collecting them puts the whole
    pytest session into trace scope. The other layers then fail in bulk — 24 failures in
    one run, none of them real, all of them looking like agent regressions. That is a
    worse outcome than not having the layer at all, so the two cannot share a session.

    They are opt-in through `CCOA_EVAL_TRAJECTORY=1`, which the documented command sets
    (docs/19 §3.9).
    """
    if os.environ.get(TRAJECTORY_FLAG):
        return

    skip = pytest.mark.skip(
        reason=f"trajectory layer is opt-in: {TRAJECTORY_FLAG}=1 "
        f"uv run deepeval test run evals/test_trajectory.py"
    )
    for item in items:
        if "trajectory" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def gemini_key() -> str:
    """The key, resolved the same way the application resolves it.

    Reading `os.environ` alone was wrong: the documented place for the key is
    `backend/.env` (docs/14 §3.3), which pydantic-settings loads but which never reaches
    `os.environ`. It appeared to work only because importing `deepeval` happens to call
    `load_dotenv()` — so the suite was relying on a side effect of a third-party import
    for its credentials, and would have started skipping silently the day that changed.
    """
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        key = Settings().gemini_api_key.get_secret_value()
    if not key:
        pytest.skip(
            "no Gemini API key: set GEMINI_API_KEY or put it in backend/.env "
            "(see backend/.env.example)"
        )
    return key


@pytest.fixture(scope="session", autouse=True)
def _preflight(gemini_key: str) -> None:
    """One cheap call before the suite, so a billing problem reads as a billing problem.

    Without this, an exhausted quota surfaces as every case failing its assertions: the
    model call fails, the graph degrades honestly, and the eval reports "never called
    search_customer" and "expected checkpoint approve, got none". That is indisputably
    the *right* behaviour from the agent and a completely misleading report — it looks
    like a catastrophic regression. It cost a debugging round to recognise, once.
    """
    import contextlib
    import json
    import urllib.error
    import urllib.request

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{EVAL_MODEL}:generateContent?key={gemini_key}"
    )
    request = urllib.request.Request(  # noqa: S310 — constant https prefix, see above
        url,
        data=json.dumps({"contents": [{"parts": [{"text": "ping"}]}]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        # The URL is built from a constant https prefix and a model name, so the scheme
        # cannot be anything else.
        urllib.request.urlopen(request, timeout=30).close()  # noqa: S310
    except urllib.error.HTTPError as exc:
        detail = ""
        with contextlib.suppress(Exception):
            detail = json.loads(exc.read()).get("error", {}).get("message", "")
        if exc.code == 429:
            pytest.skip(f"Gemini quota unavailable, so evals cannot run: {detail[:200]}")
        pytest.skip(f"Gemini returned {exc.code} on a preflight call: {detail[:200]}")
    except OSError as exc:
        pytest.skip(f"cannot reach the Gemini API: {exc}")


@pytest.fixture(scope="session")
def eval_settings(gemini_key: str, tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return Settings(
        environment="local",
        auth_mode="dev",
        gemini_api_key=gemini_key,  # type: ignore[arg-type]
        gemini_model=EVAL_MODEL,
        db_path=tmp_path_factory.mktemp("eval-db") / "app.db",
        checkpoint_db_path=tmp_path_factory.mktemp("eval-cp") / "checkpoints.db",
        enable_vector_search=False,
        # Tracing off by default even when a LangSmith key exists: an eval run is dozens
        # of graph runs, and flooding a project with them makes real traces harder to
        # find. Turn it on deliberately when investigating a regression.
        langsmith_tracing=False,
    )


@pytest.fixture(scope="session")
def corpus_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Migrate and seed once; every case gets its own copy.

    Per-case isolation is not fastidiousness — one eval approves a ticket, and without
    isolation the next eval would see it and its expectations would shift under it.
    """
    path = tmp_path_factory.mktemp("eval-corpus") / "template.db"
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{path}"
    try:
        command.upgrade(config, "head")
    finally:
        os.environ.pop("DATABASE_URL", None)

    database = Database(path)
    try:
        write(database, generate())
    finally:
        database.dispose()
    return path


@pytest.fixture
def case_db(corpus_template: Path, tmp_path: Path) -> Path:
    path = tmp_path / "app.db"
    shutil.copyfile(corpus_template, path)
    return path


@pytest.fixture(scope="session")
def model_factory(eval_settings: Settings) -> object:
    return build_model_factory(eval_settings)


@pytest.fixture(scope="session")
def judge(eval_settings: Settings) -> object:
    """The LLM that scores every judged metric.

    A custom adapter rather than DeepEval's native `GeminiModel`, because the native one
    cannot run the conversational, safety, or agentic metrics against Gemini at all —
    `evals/judge.py` documents the incompatibility and the way around it.

    Same model family as the agent under test. A *different* provider would be more
    independent, but it means a second key and a second bill; worth revisiting if scores
    ever look generous.
    """
    from evals.judge import GeminiJudge

    return GeminiJudge(eval_settings, model=EVAL_JUDGE_MODEL)


@pytest.fixture(autouse=True)
def _reset_sse_exit_signal() -> Iterator[None]:
    """Clear `sse_starlette`'s process-global shutdown event between tests.

    The same fix as `tests/api/conftest.py`, needed here for the same reason: the library
    caches an `asyncio.Event` on a module-level singleton, each `TestClient` runs its own
    event loop, and the second streaming test in a module inherits an event bound to the
    first one's loop. The symptom is "bound to a different event loop" on every test
    after the first — which reads as a streaming regression and is not one.

    Deliberately duplicated rather than shared: `evals` importing from `tests` would tie
    the opt-in suite to the gate suite's layout for six lines.
    """
    from sse_starlette.sse import AppStatus

    AppStatus.should_exit_event = None
    yield
    AppStatus.should_exit_event = None


@pytest.fixture(autouse=True)
def _quiet_logs() -> Iterator[None]:
    """Evals are about the agent's output, not its log lines."""
    import logging

    previous = logging.getLogger().level
    logging.getLogger().setLevel(logging.WARNING)
    yield
    logging.getLogger().setLevel(previous)


def make_model(factory: object) -> BaseChatModel:
    return factory()  # type: ignore[operator, no-any-return]
