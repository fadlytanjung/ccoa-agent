"""Shared fixtures.

Every fixture here builds its own database and its own dependencies. Nothing is module
level and nothing is shared between tests, so a test can never inherit another test's
rows — which matters more than usual here, because the corpus is deterministic and a
leaked write would look like a generator bug.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from langchain_core.language_models import BaseChatModel

from app.agents.registry import SkillRegistry, default_skill_root
from app.config import Settings, reset_settings
from app.db.engine import Database
from app.domain.actor import Actor
from app.domain.enums import Group
from app.graph.deps import GraphDependencies
from app.graph.tools import ALL_TOOL_NAMES, ToolBox, ToolContext
from app.repositories import Repositories
from app.seed import generate, write
from app.services.audit import AuditService
from app.services.retrieval import RetrievalService
from tests.stub_model import StubModel

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolate_settings() -> Iterator[None]:
    """Keep a developer's real `.env` out of the tests.

    Without this the suite would pick up a live API key and a real database path from
    whoever happens to be running it, and pass or fail for reasons unrelated to the code.
    """
    reset_settings()
    yield
    reset_settings()


@pytest.fixture(scope="session")
def seeded_db_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Migrate and seed once per session; every test copies the file.

    Seeding takes a second or so. Copying a 10 MB file does not.
    """
    path = tmp_path_factory.mktemp("corpus") / "template.db"
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{path}"
    try:
        command.upgrade(config, "head")
    finally:
        os.environ.pop("DATABASE_URL", None)

    db = Database(path)
    try:
        write(db, generate())
    finally:
        db.dispose()
    return path


@pytest.fixture
def db(seeded_db_template: Path, tmp_path: Path) -> Iterator[Database]:
    import shutil

    path = tmp_path / "app.db"
    shutil.copyfile(seeded_db_template, path)
    database = Database(path)
    yield database
    database.dispose()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="local",
        auth_mode="dev",
        db_path=tmp_path / "app.db",
        checkpoint_db_path=tmp_path / "checkpoints.db",
        gemini_api_key="test-key-not-used",  # type: ignore[arg-type]
        enable_vector_search=False,
    )


@pytest.fixture
def repos(db: Database) -> Repositories:
    return Repositories.build(db)


@pytest.fixture
def registry() -> SkillRegistry:
    return SkillRegistry(default_skill_root(), known_tools=ALL_TOOL_NAMES)


@pytest.fixture
def toolbox(
    db: Database, repos: Repositories, settings: Settings, registry: SkillRegistry
) -> ToolBox:
    retrieval = RetrievalService(db, repos, settings)
    return ToolBox(
        ToolContext(repos=repos, settings=settings, registry=registry, retrieval=retrieval)
    )


@pytest.fixture
def stub_model() -> StubModel:
    return StubModel()


@pytest.fixture
def deps(
    db: Database,
    repos: Repositories,
    settings: Settings,
    registry: SkillRegistry,
    toolbox: ToolBox,
    stub_model: StubModel,
) -> GraphDependencies:
    """Dependencies with a stubbed model — no network, no key, no nondeterminism."""

    def factory(
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_output_tokens: int = 2048,
    ) -> BaseChatModel:
        del model, temperature, max_output_tokens
        return stub_model

    return GraphDependencies(
        settings=settings,
        database=db,
        repos=repos,
        registry=registry,
        toolbox=toolbox,
        audit=AuditService(db, repos.audit),
        model_factory=factory,
    )


@pytest.fixture
def agent_actor() -> Actor:
    return Actor(sub="agent-1", email="agent@example.com", groups=(Group.AGENT,))


@pytest.fixture
def supervisor_actor() -> Actor:
    return Actor(sub="sup-1", email="sup@example.com", groups=(Group.AGENT, Group.SUPERVISOR))


def run_config(actor: Actor, thread_id: str = "test-thread") -> dict[str, Any]:
    return {
        "configurable": {
            "thread_id": thread_id,
            "actor": actor.to_config(),
            "trace_id": f"trace-{thread_id}",
        }
    }


@pytest.fixture(scope="session")
def corpus() -> Any:
    """The generated corpus, once. Generation is pure, so sharing it is safe."""
    from app.seed import generate

    return generate()
