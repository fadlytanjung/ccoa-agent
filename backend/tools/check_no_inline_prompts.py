#!/usr/bin/env python
"""Fail the build if prompt text has crept into Python — docs/17 §3.9.

Conventions erode; the check does not. It walks the AST of the directories where
prompts would plausibly hide and rejects any string literal over the limit.

**Docstrings are exempt, and that exemption is load-bearing rather than lazy.** No
docstring in this codebase ever reaches the model: system prompts come from
``SKILL.md`` bodies and tool descriptions from ``tools.yaml``, both loaded by the
registry. A prompt hidden in a docstring would therefore have no way to be used. The
exemption is what lets the graph explain itself at the length it needs to.

The rule covers system prompts, tool descriptions, routing policy text, few-shot
examples, and output formats. It does not cover log messages, exception strings, or SQL.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

MAX_LITERAL = 200
CHECKED_DIRS = ("app/graph", "app/agents")
ALLOW_MARKER = "noqa: inline-prompt"


class LiteralVisitor(ast.NodeVisitor):
    """Collects long string literals that are not docstrings."""

    def __init__(self, source_lines: list[str]) -> None:
        self.source_lines = source_lines
        self.findings: list[tuple[int, int, str]] = []
        self._docstrings: set[int] = set()

    def _note_docstring(self, node: ast.AST) -> None:
        body = getattr(node, "body", None)
        if not body:
            return
        first = body[0]
        is_docstring = (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        )
        if is_docstring:
            self._docstrings.add(id(first.value))  # type: ignore[attr-defined]

    def visit_Module(self, node: ast.Module) -> None:
        self._note_docstring(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._note_docstring(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._note_docstring(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._note_docstring(node)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, str) or id(node) in self._docstrings:
            return
        if len(node.value) <= MAX_LITERAL:
            return

        line = node.lineno
        # An annotated exception is allowed; the annotation is the review trail.
        window = self.source_lines[max(0, line - 1) : line + 1]
        if any(ALLOW_MARKER in text for text in window):
            return

        preview = " ".join(node.value.split())[:70]
        self.findings.append((line, len(node.value), preview))


def check_file(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"{path}: could not parse — {exc}"]

    visitor = LiteralVisitor(source.splitlines())
    visitor.visit(tree)
    return [
        f"{path}:{line}: string literal of {size} characters (limit {MAX_LITERAL}) — {preview!r}"
        for line, size, preview in visitor.findings
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)

    problems: list[str] = []
    checked = 0
    for relative in CHECKED_DIRS:
        directory = args.root / relative
        if not directory.is_dir():
            print(f"warning: {directory} does not exist", file=sys.stderr)
            continue
        for path in sorted(directory.rglob("*.py")):
            checked += 1
            problems.extend(check_file(path))

    if problems:
        print("Prompt text must live in SKILL.md or tools.yaml, not in Python.\n")
        for problem in problems:
            print(f"  {problem}")
        print(
            f"\n{len(problems)} violation(s). See docs/17-agent-skills.md §3.9. "
            f"Annotate a genuine exception with '# {ALLOW_MARKER}'."
        )
        return 1

    print(f"no inline prompts: {checked} files checked under {', '.join(CHECKED_DIRS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
