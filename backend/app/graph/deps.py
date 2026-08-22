"""What the graph needs from the rest of the application.

Bundled into one object and injected, for the same reason the checkpointer is: the
graph must be constructible three ways — under the Agent Server, under FastAPI, and
under test — without knowing which (docs/14 §3.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.agents.registry import SkillRegistry, default_skill_root
from app.config import Settings, get_settings
from app.db.engine import Database
from app.graph.tools import ALL_TOOL_NAMES, ToolBox, ToolContext, assert_in_step
from app.repositories import Repositories
from app.services.audit import AuditService
from app.services.llm import ModelFactory, build_model_factory
from app.services.retrieval import RetrievalService


@dataclass(frozen=True, slots=True)
class GraphDependencies:
    settings: Settings
    database: Database
    repos: Repositories
    registry: SkillRegistry
    toolbox: ToolBox
    audit: AuditService
    model_factory: ModelFactory

    @classmethod
    def build(
        cls,
        settings: Settings | None = None,
        *,
        database: Database | None = None,
        skill_root: Path | None = None,
        model_factory: ModelFactory | None = None,
    ) -> GraphDependencies:
        resolved = settings or get_settings()
        db = database or Database(resolved.db_path)
        repos = Repositories.build(db)

        # Both checks are boot-time and both are fatal. A skill naming a tool that does
        # not exist, or a description with no tool, are the two ways this layer drifts
        # out of step without anything failing until a user asks a question.
        assert_in_step(ALL_TOOL_NAMES)
        registry = SkillRegistry(skill_root or default_skill_root(), known_tools=ALL_TOOL_NAMES)

        retrieval = RetrievalService(db, repos, resolved)
        toolbox = ToolBox(
            ToolContext(repos=repos, settings=resolved, registry=registry, retrieval=retrieval)
        )
        return cls(
            settings=resolved,
            database=db,
            repos=repos,
            registry=registry,
            toolbox=toolbox,
            audit=AuditService(db, repos.audit),
            model_factory=model_factory or build_model_factory(resolved),
        )
