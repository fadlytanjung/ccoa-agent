"""Skill registry — docs/17 §3.10.

The token-budget test is a real test, not a nicety: tier-1 descriptions ride in every
orchestrator call, so unbounded growth there is a per-request cost regression that no
functional test would catch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.registry import (
    MAX_BODY_CHARS,
    MAX_TOTAL_DESCRIPTION_CHARS,
    SkillError,
    SkillRegistry,
    default_skill_root,
    parse_skill_file,
)
from app.graph.tools import ALL_TOOL_NAMES
from app.graph.tools.descriptions import DescriptionError, assert_in_step, load_descriptions

EXPECTED_SKILLS = ("history", "investigator", "orchestrator", "profile", "resolution")


class TestLoading:
    def test_every_skill_parses_and_validates(self, registry: SkillRegistry) -> None:
        assert registry.names() == EXPECTED_SKILLS

    def test_every_declared_tool_exists(self, registry: SkillRegistry) -> None:
        for name in registry.names():
            assert set(registry.get(name).tools) <= ALL_TOOL_NAMES

    def test_an_unknown_tool_fails_boot(self, tmp_path: Path) -> None:
        skill = tmp_path / "broken"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\n"
            "name: broken\nversion: 1.0.0\n"
            "description: A skill that names a tool which does not exist anywhere.\n"
            "tools:\n  - get_polciy\n"
            "---\n\n## Role\n\nBody.\n"
        )
        with pytest.raises(SkillError, match="unknown tools"):
            SkillRegistry(tmp_path, known_tools=ALL_TOOL_NAMES)

    def test_name_must_match_the_directory(self, tmp_path: Path) -> None:
        skill = tmp_path / "profile"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: history\nversion: 1.0.0\n"
            "description: A description long enough to satisfy the minimum length rule.\n"
            "---\n\n## Role\n\nBody.\n"
        )
        with pytest.raises(SkillError, match="does not match directory"):
            SkillRegistry(tmp_path)

    def test_a_missing_reference_fails_boot(self, tmp_path: Path) -> None:
        skill = tmp_path / "profile"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: profile\nversion: 1.0.0\n"
            "description: A description long enough to satisfy the minimum length rule.\n"
            "references:\n  - references/absent.md\n"
            "---\n\n## Role\n\nBody.\n"
        )
        with pytest.raises(SkillError, match="does not exist"):
            SkillRegistry(tmp_path)

    def test_unknown_frontmatter_keys_are_an_error(self, tmp_path: Path) -> None:
        skill = tmp_path / "profile"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: profile\nversion: 1.0.0\n"
            "description: A description long enough to satisfy the minimum length rule.\n"
            "temprature: 0.5\n"  # a typo that would otherwise silently do nothing
            "---\n\n## Role\n\nBody.\n"
        )
        with pytest.raises(SkillError, match="invalid frontmatter"):
            SkillRegistry(tmp_path)

    def test_an_empty_body_is_rejected(self) -> None:
        with pytest.raises(SkillError, match="body is empty"):
            parse_skill_file("---\nname: x\n---\n\n   \n", source="x/SKILL.md")

    def test_missing_frontmatter_is_rejected(self) -> None:
        with pytest.raises(SkillError, match="missing YAML frontmatter"):
            parse_skill_file("## Role\n\nJust a body.\n", source="x/SKILL.md")


class TestProgressiveDisclosure:
    def test_descriptions_are_deterministically_ordered(self, registry: SkillRegistry) -> None:
        first = [d.name for d in registry.descriptions()]
        second = [d.name for d in registry.descriptions()]
        assert first == second == sorted(first)

    def test_tier_one_stays_within_budget(self, registry: SkillRegistry) -> None:
        total = sum(len(d.description) for d in registry.descriptions())
        assert total <= MAX_TOTAL_DESCRIPTION_CHARS

    def test_no_body_is_oversized(self, registry: SkillRegistry) -> None:
        for name in registry.names():
            assert len(registry.get(name).body) <= MAX_BODY_CHARS

    def test_references_load_on_demand(self, registry: SkillRegistry) -> None:
        body = registry.reference("investigator", "references/failure-codes.md")
        assert "DOC_UNREADABLE" in body

    def test_an_undeclared_reference_is_refused(self, registry: SkillRegistry) -> None:
        with pytest.raises(SkillError, match="not a declared reference"):
            registry.reference("profile", "references/failure-codes.md")

    @pytest.mark.parametrize("path", ["../../secrets", "../orchestrator/SKILL.md", "/etc/passwd"])
    def test_traversal_is_rejected(self, registry: SkillRegistry, path: str) -> None:
        with pytest.raises(SkillError):
            registry.reference("investigator", path)


class TestTemplates:
    def test_ticket_draft_renders(self, registry: SkillRegistry) -> None:
        rendered = registry.render(
            "resolution",
            "templates/ticket-draft.md.j2",
            {
                "customer": {"full_name": "John Tan", "customer_id": "CUST-000042"},
                "case": {
                    "case_id": "CASE-000008",
                    "title": "T",
                    "status": "open",
                    "priority": "high",
                },
                "claim": {
                    "claim_id": "CLM-00000117",
                    "status": "submission_failed",
                    "failure_code": "DOC_UNREADABLE",
                },
                "priority": "high",
                "category": "claim_issue",
                "problem": "It failed three times.",
                "next_action": "Manual document review.",
                "already_attempted": ["Re-upload"],
                "evidence": [{"ref": "claim:CLM-00000117", "summary": "failed"}],
                "actor_email": "agent@example.com",
            },
        )
        assert "CUST-000042" in rendered
        assert "CLM-00000117" in rendered
        assert "Manual document review." in rendered

    def test_escalation_brief_renders(self, registry: SkillRegistry) -> None:
        rendered = registry.render(
            "resolution",
            "templates/escalation-brief.md.j2",
            {
                "customer": {"full_name": "John Tan", "customer_id": "CUST-000042", "tier": "gold"},
                "case": {
                    "case_id": "CASE-000008",
                    "title": "T",
                    "status": "open",
                    "priority": "high",
                    "owner": "C. Lim",
                },
                "escalate_to": "Tier 2",
                "priority": "high",
                "reason": "Three failed attempts.",
                "steps_taken": ["Advised re-upload"],
                "decision_requested": "Manual override?",
                "evidence": [{"ref": "case:CASE-000008", "summary": "open"}],
                "actor_email": "agent@example.com",
            },
        )
        assert "Tier 2" in rendered
        assert "Manual override?" in rendered

    def test_an_undeclared_template_is_refused(self, registry: SkillRegistry) -> None:
        with pytest.raises(SkillError, match="not a declared template"):
            registry.render("profile", "templates/anything.md.j2", {})

    def test_a_missing_variable_fails_loudly(self, registry: SkillRegistry) -> None:
        # StrictUndefined: a silently-empty field in a ticket a human is about to
        # approve is worse than a render error the graph can fall back from.
        with pytest.raises(SkillError, match="render failed"):
            registry.render("resolution", "templates/ticket-draft.md.j2", {})


class TestToolDescriptions:
    def test_descriptions_and_registry_are_in_step(self) -> None:
        assert_in_step(ALL_TOOL_NAMES)

    def test_a_tool_without_a_description_fails(self) -> None:
        with pytest.raises(DescriptionError, match="no description"):
            assert_in_step(ALL_TOOL_NAMES | {"invented_tool"})

    def test_every_description_is_prose_not_a_placeholder(self) -> None:
        for name, entry in load_descriptions().items():
            assert len(entry.description.split()) >= 10, name


def test_digests_change_when_a_skill_changes(tmp_path: Path) -> None:
    """Digests are logged per run so an output regression is attributable."""
    skill = tmp_path / "profile"
    skill.mkdir()
    header = (
        "---\nname: profile\nversion: 1.0.0\n"
        "description: A description long enough to satisfy the minimum length rule.\n"
        "---\n\n## Role\n\n"
    )
    (skill / "SKILL.md").write_text(header + "First body.\n")
    before = SkillRegistry(tmp_path).get("profile").digest

    (skill / "SKILL.md").write_text(header + "Second body.\n")
    after = SkillRegistry(tmp_path).get("profile").digest

    assert before != after


def test_the_shipped_skills_load_from_the_real_root() -> None:
    registry = SkillRegistry(default_skill_root(), known_tools=ALL_TOOL_NAMES)
    assert set(registry.names()) == set(EXPECTED_SKILLS)
