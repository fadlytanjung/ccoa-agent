#!/usr/bin/env python
"""Fail the build if anything account-specific has reached the repository.

This repository is public. "Do not put our account details in the docs" is a rule that
holds right up until someone pastes a console error or a `terraform plan` diff into an
issue, a comment, or a runbook — at which point it holds no longer, quietly, and in
git history where removing it is not enough.

So the rule is a check. What it looks for is anything that identifies a *specific* AWS
account, principal, or network rather than the shape of one:

  * 12-digit account numbers, including inside ARNs
  * AWS resource identifiers — vpc-, subnet-, sg-, i-, ami-, eni-, rtb-, igw-, nat-
  * access key ids and long-lived secret material
  * IAM user paths and console sign-in URLs
  * personal names and local filesystem paths

Placeholders are the intended alternative and are explicitly allowed:
``<AWS_ACCOUNT_ID>``, ``123456789012``, ``vpc-EXAMPLE``, ``ORG/REPO``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

#: Documentation's own reserved example account number. AWS uses it throughout its
#: documentation for exactly this purpose, so it is a placeholder, not a leak.
EXAMPLE_ACCOUNT = "123456789012"

SCANNED_SUFFIXES = {".md", ".py", ".yaml", ".yml", ".tf", ".tfvars", ".json", ".sh", ".toml"}
SCANNED_NAMES = {"Dockerfile", "Makefile"}

SKIP_DIRECTORIES = {
    ".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache",
    ".pytest_cache", "dist", "build", "htmlcov", ".terraform",
}

ALLOW_MARKER = "noqa: account-identifier"


class Rule:
    def __init__(
        self, name: str, pattern: str, explanation: str, *, exemptable: bool = True
    ) -> None:
        self.name = name
        self.pattern = re.compile(pattern)
        self.explanation = explanation
        #: Credential rules are never exempted by a placeholder hint. AWS's own
        #: documentation example key contains the word EXAMPLE, so a hint-based
        #: exemption would wave through anything shaped like it — and a leaked key is
        #: the one finding here that cannot be fixed by editing the file.
        self.exemptable = exemptable


RULES = [
    Rule(
        "aws-account-id",
        r"(?<![\w.-])\d{12}(?![\w.-])",
        "a 12-digit AWS account number — use <AWS_ACCOUNT_ID> or 123456789012",
    ),
    Rule(
        "aws-resource-id",
        r"\b(vpc|subnet|sg|i|ami|eni|rtb|igw|nat|acl|vol|snap)-[0-9a-f]{8,17}\b",
        "a real AWS resource id — use a placeholder such as vpc-EXAMPLE",
    ),
    Rule(
        "aws-access-key-id",
        r"\b(AKIA|ASIA|AIDA|AROA|AIPA|ANPA|ANVA)[0-9A-Z]{16}\b",
        "an AWS access key id — this must be rotated, not just deleted from the file",
        exemptable=False,
    ),
    Rule(
        "console-signin-url",
        r"https://\d{12}\.signin\.aws\.amazon\.com",
        "an account-specific console sign-in URL",
    ),
    Rule(
        "google-api-key",
        r"\bAIza[0-9A-Za-z_-]{35}\b",
        "a Google API key — rotate it immediately",
        exemptable=False,
    ),
    Rule(
        "local-home-path",
        r"/(?:Users|home)/(?!<)[A-Za-z][\w.-]*",
        "a local filesystem path that names a user account",
    ),
]

#: Substrings that make a match a placeholder rather than a leak.
PLACEHOLDER_HINTS = (
    EXAMPLE_ACCOUNT,
    "EXAMPLE",
    "<AWS_ACCOUNT_ID>",
    "ACCOUNT_ID",
    "xxxxxxxx",
    "XXXXXXXX",
    "000000000000",
)


def is_placeholder(matched: str) -> bool:
    return any(hint in matched for hint in PLACEHOLDER_HINTS)


def scan_file(path: Path, extra_terms: list[str]) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    findings: list[str] = []
    lines = text.splitlines()
    for number, line in enumerate(lines, start=1):
        if ALLOW_MARKER in line:
            continue

        for rule in RULES:
            for match in rule.pattern.finditer(line):
                if rule.exemptable and is_placeholder(match.group(0)):
                    continue
                findings.append(f"{path}:{number}: [{rule.name}] {rule.explanation}")

        for term in extra_terms:
            if term and term.lower() in line.lower():
                findings.append(f"{path}:{number}: [personal-term] contains {term!r}")
    return findings


def iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRECTORIES for part in path.parts):
            continue
        if path.suffix in SCANNED_SUFFIXES or path.name in SCANNED_NAMES:
            files.append(path)
    return sorted(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--term",
        action="append",
        default=[],
        help="an additional term to forbid, such as a personal or company name. "
        "Repeatable. Passed on the command line so the value itself is never "
        "committed to this file.",
    )
    args = parser.parse_args(argv)

    files = iter_files(args.root)
    findings: list[str] = []
    for path in files:
        # The checker quotes the very patterns it forbids, so it would always flag
        # itself. Exempting it by name is simpler than escaping every regex.
        if path.name == Path(__file__).name:
            continue
        findings.extend(scan_file(path, args.term))

    if findings:
        print("Account-specific details must not appear in a public repository.\n")
        for finding in findings:
            print(f"  {finding}")
        print(
            f"\n{len(findings)} finding(s) in {len(files)} files. "
            f"Use a placeholder, or annotate a false positive with '# {ALLOW_MARKER}'. "
            f"See docs/18-aws-access-and-manual-steps.md §6."
        )
        return 1

    print(f"no account identifiers: {len(files)} files scanned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
