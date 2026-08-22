"""Skill registry — docs/17 §3.7.

Loads, validates, and caches every skill at boot. **Any failure aborts startup.** A
malformed skill must not reach production as a runtime surprise on the first user
request, and a skill listing a tool that does not exist would otherwise offer the model
a capability that silently fails.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import yaml
from jinja2 import BaseLoader, Environment, StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment
from pydantic import ValidationError

from app.agents.schema import Skill, SkillDescriptor, SkillFrontmatter

log = logging.getLogger(__name__)

SKILL_FILENAME = "SKILL.md"
FRONTMATTER_DELIMITER = "---"

#: Tier-1 descriptions ride in *every* orchestrator call, so unbounded growth there is a
#: per-request cost regression no functional test would catch (docs/17 §3.10).
MAX_TOTAL_DESCRIPTION_CHARS = 6000
MAX_BODY_CHARS = 12000


class SkillError(RuntimeError):
    """A skill could not be loaded. Always fatal at boot."""


def parse_skill_file(text: str, *, source: str) -> tuple[dict[str, Any], str]:
    """Split ``SKILL.md`` into its YAML frontmatter and Markdown body."""
    if not text.startswith(FRONTMATTER_DELIMITER):
        raise SkillError(f"{source}: missing YAML frontmatter")

    parts = text.split(FRONTMATTER_DELIMITER, 2)
    if len(parts) < 3:
        raise SkillError(f"{source}: frontmatter is not terminated by '---'")

    try:
        loaded = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise SkillError(f"{source}: frontmatter is not valid YAML — {exc}") from exc

    if not isinstance(loaded, dict):
        raise SkillError(f"{source}: frontmatter must be a mapping")

    body = parts[2].strip()
    if not body:
        raise SkillError(f"{source}: body is empty — the body is the system prompt")
    return loaded, body


def _digest_directory(directory: Path) -> str:
    """SHA-256 over every file in the skill directory, in sorted order."""
    hasher = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        hasher.update(path.relative_to(directory).as_posix().encode())
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


class SkillRegistry:
    """Owns every skill. One instance per process, built in the app lifespan."""

    def __init__(
        self,
        root: Path,
        *,
        known_tools: frozenset[str] | None = None,
        strict: bool = True,
    ) -> None:
        self.root = root
        self.known_tools = known_tools
        self.strict = strict
        self._skills: dict[str, Skill] = {}
        self._env: Environment = SandboxedEnvironment(
            loader=BaseLoader(),
            undefined=StrictUndefined,
            # Markdown, not HTML — escaping would corrupt the ticket body a human is
            # about to approve.
            autoescape=False,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.load()

    # -- loading -----------------------------------------------------------
    def load(self) -> None:
        if not self.root.is_dir():
            raise SkillError(f"skill root does not exist: {self.root}")

        skills: dict[str, Skill] = {}
        for directory in sorted(p for p in self.root.iterdir() if p.is_dir()):
            skill_file = directory / SKILL_FILENAME
            if not skill_file.is_file():
                continue
            skill = self._load_one(directory, skill_file)
            if skill.name in skills:
                raise SkillError(f"two skills declare name {skill.name!r}")
            skills[skill.name] = skill

        if not skills:
            raise SkillError(f"no skills found under {self.root}")

        self._check_budgets(skills)
        self._skills = skills

        for skill in skills.values():
            log.info("skill loaded %s@%s digest=%s", skill.name, skill.version, skill.digest[:12])

    def _load_one(self, directory: Path, skill_file: Path) -> Skill:
        source = str(skill_file.relative_to(self.root.parent))
        raw, body = parse_skill_file(skill_file.read_text(encoding="utf-8"), source=source)

        try:
            frontmatter = SkillFrontmatter.model_validate(raw)
        except ValidationError as exc:
            raise SkillError(f"{source}: invalid frontmatter — {exc}") from exc

        if frontmatter.name != directory.name:
            raise SkillError(
                f"{source}: frontmatter name {frontmatter.name!r} does not match "
                f"directory {directory.name!r}"
            )

        # An unknown tool name fails the container at boot with a clear message, rather
        # than offering the model a tool that does not exist (docs/17 §3.4).
        if self.known_tools is not None:
            unknown = sorted(set(frontmatter.tools) - self.known_tools)
            if unknown:
                raise SkillError(
                    f"{source}: declares unknown tools {unknown}. "
                    f"Known tools: {sorted(self.known_tools)}"
                )

        for relative in (*frontmatter.references, *frontmatter.templates):
            if not self._resolve(directory, relative).is_file():
                raise SkillError(f"{source}: declared path does not exist — {relative}")

        return Skill(
            frontmatter=frontmatter,
            body=body,
            digest=_digest_directory(directory),
        )

    def _check_budgets(self, skills: dict[str, Skill]) -> None:
        total = sum(len(s.frontmatter.description) for s in skills.values())
        if total > MAX_TOTAL_DESCRIPTION_CHARS:
            raise SkillError(
                f"tier-1 descriptions total {total} characters, over the "
                f"{MAX_TOTAL_DESCRIPTION_CHARS} budget — they ride in every "
                f"orchestrator call"
            )
        for skill in skills.values():
            if len(skill.body) > MAX_BODY_CHARS:
                raise SkillError(
                    f"{skill.name}: body is {len(skill.body)} characters, over the "
                    f"{MAX_BODY_CHARS} budget"
                )

    def _resolve(self, directory: Path, relative: str) -> Path:
        """Resolve a path **inside** the skill directory.

        A traversal attempt is rejected, not merely normalised (docs/17 §3.5). The
        comparison is on the fully resolved path, so symlinks cannot escape either.
        """
        base = directory.resolve()
        candidate = (base / relative).resolve()
        if not candidate.is_relative_to(base):
            raise SkillError(f"path escapes the skill directory: {relative!r}")
        return candidate

    # -- access ------------------------------------------------------------
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._skills))

    def descriptions(self) -> list[SkillDescriptor]:
        """Tier 1 — the orchestrator's delegation menu, deterministically ordered."""
        return [self._skills[name].descriptor() for name in self.names()]

    def get(self, name: str) -> Skill:
        """Tier 2 — the full skill."""
        try:
            return self._skills[name]
        except KeyError:
            raise SkillError(f"unknown skill: {name!r}") from None

    def has(self, name: str) -> bool:
        return name in self._skills

    def reference(self, name: str, relative: str) -> str:
        """Tier 3 — a reference document, loaded on demand.

        Only paths the skill *declared* are readable. Declaring the allowed set up front
        means the traversal guard is a second line of defence rather than the only one.
        """
        skill = self.get(name)
        if relative not in skill.frontmatter.references:
            raise SkillError(f"{name}: {relative!r} is not a declared reference")
        return self._resolve(self.root / name, relative).read_text(encoding="utf-8")

    def render(self, name: str, template: str, context: dict[str, Any]) -> str:
        """Render one of the skill's declared Jinja2 templates.

        Rendered with an explicit context dict, never ``**state`` — a template must not
        be able to reach into graph state it was not handed.
        """
        skill = self.get(name)
        if template not in skill.frontmatter.templates:
            raise SkillError(f"{name}: {template!r} is not a declared template")
        source = self._resolve(self.root / name, template).read_text(encoding="utf-8")
        try:
            return self._env.from_string(source).render(**context)
        except TemplateError as exc:
            raise SkillError(f"{name}/{template}: render failed — {exc}") from exc

    def digests(self) -> dict[str, str]:
        """``name@version -> digest``, for the boot log and ``/api/v1/meta``."""
        return {f"{s.name}@{s.version}": s.digest for s in self._skills.values()}


def default_skill_root() -> Path:
    return Path(__file__).parent / "skills"
