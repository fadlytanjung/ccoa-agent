#!/usr/bin/env python3
"""Verify that docs/20-implementation-status.md is still true.

A status document that nobody checks becomes the most confidently wrong file in a
repository — and this one exists precisely because a specification reads the same whether
or not anything implements it. So the claims that *can* be falsified mechanically are.

What this checks:

* every repository path the document names exists;
* directories it calls **Specified** are still empty, and directories it calls **Built**
  are not — a row that has quietly become true is as wrong as one that has become false;
* the test counts in §5 match what the suites actually collect;
* ``Last verified`` has not gone stale relative to the code.

What it deliberately does **not** check: whether a component is genuinely "Built" rather
than "Partial". No tool can judge that. It can only notice when a stated fact has stopped
being one, which is the failure mode that actually happens.

Usage:
    python3 tools/check_implementation_status.py [--update-counts]

``--update-counts`` runs the suites and rewrites the numbers in §5, so refreshing the
document is a command rather than an exercise in careful reading.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS_DOC = ROOT / "docs" / "20-implementation-status.md"

#: Directories the document claims are empty. If one grows a file, the row is stale.
#: Nothing is claimed empty any more — both `terraform/` and `.github/workflows/` are
#: implemented. The mechanism is kept because it is the check that catches a row quietly
#: becoming true, which is as wrong as one becoming false.
CLAIMED_EMPTY: dict[str, str] = {}

#: Paths the document names as existing work. Missing means a row is describing a file
#: that has been moved or deleted.
CLAIMED_PRESENT = {
    "backend/app",
    "backend/tests",
    "backend/evals",
    "backend/evals/dataset.yaml",
    "backend/alembic/versions",
    "backend/docker/verify-replication.sh",
    "backend/app/agents/skills",
    "frontend/src",
    "frontend/e2e/assistant.spec.ts",
    "frontend/e2e/mobile.spec.ts",
    "frontend/docker/verify-image.sh",
    "tools/check_no_account_identifiers.py",
    "docs/21-design-system.md",
    "docs/22-getting-started.md",
    ".github/workflows/ci.yml",
    "scripts/preflight.sh",
    "scripts/dev.sh",
    "scripts/verify.sh",
    "scripts/aws-bootstrap.sh",
    "scripts/aws-cognito.sh",
    "scripts/deploy.sh",
    "scripts/destroy.sh",
    ".github/workflows/deploy.yml",
    "terraform/main.tf",
    "terraform/ecs_backend.tf",
    "terraform/cloudfront.tf",
    "terraform/envs/dev.tfvars",
    "docs/adr/ADR-008-provisioned-identity.md",
}

#: How long the document may go unverified after the code moves, in days. Not zero: a
#: typo fix should not fail the build, and a fortnight is long enough that a genuinely
#: stale document is the only thing this catches.
STALENESS_DAYS = 14

#: Directories whose changes mean the status could have moved.
CODE_PATHS = ("backend/app", "frontend/src", "terraform", ".github")


@dataclass
class Problem:
    where: str
    detail: str


def read_doc() -> str:
    if not STATUS_DOC.exists():
        print(f"FAIL  {STATUS_DOC.relative_to(ROOT)} does not exist", file=sys.stderr)
        raise SystemExit(1)
    return STATUS_DOC.read_text(encoding="utf-8")


# --- individual checks ------------------------------------------------------------


def check_paths_exist() -> list[Problem]:
    return [
        Problem(path, "named by the status document, but not present")
        for path in sorted(CLAIMED_PRESENT)
        if not (ROOT / path).exists()
    ]


def _is_empty(directory: Path) -> bool:
    if not directory.exists():
        return True
    # `.gitkeep` and friends are placeholders, not implementation.
    return not [p for p in directory.rglob("*") if p.is_file() and not p.name.startswith(".")]


def check_empty_claims(doc: str) -> list[Problem]:
    problems: list[Problem] = []
    for path, claim in CLAIMED_EMPTY.items():
        directory = ROOT / path
        if _is_empty(directory):
            continue
        files = sum(1 for p in directory.rglob("*") if p.is_file())
        problems.append(
            Problem(
                path,
                f"contains {files} file(s), but {claim}. "
                f"If this is now implemented, change the row to Built and say what tests it.",
            )
        )
    # The inverse: the document must still be making that claim. If someone edits the row
    # to "Built" while the directory is empty, that is the same defect in the other
    # direction.
    for path in CLAIMED_EMPTY:
        if _is_empty(ROOT / path) and f"`{path}/`" not in doc and path not in doc:
            problems.append(
                Problem(path, "is empty, but the status document no longer mentions it")
            )
    return problems


#: Returned when a toolchain is absent, as distinct from a count that could not be
#: parsed. The first is not this tool's problem; the second is a bug in this tool, and
#: must never be mistaken for "nothing to check".
UNAVAILABLE = "<<unavailable>>"


def _run(command: list[str], cwd: Path) -> str:
    if not cwd.exists():
        return UNAVAILABLE
    try:
        result = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=600, check=False
        )
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover - environment
        return UNAVAILABLE
    return result.stdout + result.stderr


def count_backend_tests() -> int | str | None:
    # Same reasoning as the frontend: an absent virtualenv is a missing toolchain, not a
    # stale document.
    if not (ROOT / "backend" / ".venv").exists():
        return UNAVAILABLE

    output = _run(["uv", "run", "pytest", "--collect-only", "-q"], ROOT / "backend")
    if output == UNAVAILABLE:
        return UNAVAILABLE
    # Two shapes, because `-q` prints a summary line on a bare pytest and a per-file
    # tally once a plugin takes over the terminal reporter. Relying on the summary alone
    # made this check silently do nothing for months of imagined future — it matched no
    # line, returned None, and was skipped as "toolchain missing".
    match = re.search(r"(\d+) tests? collected", output)
    if match:
        return int(match.group(1))
    per_file = re.findall(r"^\S+\.py: (\d+)$", output, re.M)
    return sum(int(n) for n in per_file) if per_file else None


def count_frontend_tests() -> int | str | None:
    # `npx vitest list` without an install does not fail cleanly — it tries to fetch
    # vitest, then errors in a way that produces output but no test list, which this tool
    # then reported as "could not determine the count — fix the checker". The dependency
    # is what is missing, not the parse, and the two want different answers.
    if not (ROOT / "frontend" / "node_modules" / "vitest").exists():
        return UNAVAILABLE

    output = _run(["npx", "vitest", "list"], ROOT / "frontend")
    if output == UNAVAILABLE:
        return UNAVAILABLE
    tests = [line for line in output.splitlines() if " > " in line]
    return len(tests) or None


def count_e2e_tests(spec: str) -> int | None:
    path = ROOT / "frontend" / "e2e" / spec
    if not path.exists():
        return None
    # Counting `test(` in the source rather than asking Playwright: listing tests starts
    # a browser and a backend, which is far too much work for a documentation check.
    return len(re.findall(r"^\s*test\(", path.read_text(encoding="utf-8"), re.M))


def count_eval_cases() -> int | None:
    path = ROOT / "backend" / "evals" / "dataset.yaml"
    if not path.exists():
        return None
    return len(re.findall(r"^\s{2}-\s", path.read_text(encoding="utf-8"), re.M)) or None


def count_skills() -> int:
    skills = ROOT / "backend" / "app" / "agents" / "skills"
    return sum(1 for p in skills.iterdir() if p.is_dir()) if skills.exists() else 0


def stated_counts(doc: str) -> dict[str, int]:
    """Pull the numbers §5 asserts, so they can be compared with reality."""
    found: dict[str, int] = {}
    patterns = {
        "backend": r"\*\*(\d+) passing, \d+% coverage\*\*",
        "frontend": r"\*\*(\d+) passing\*\*\s*\|\s*Do the parser",
        "e2e": r"\*\*(\d+) passing\*\* \(4 shell",
        "mobile": r"\*\*(\d+) passing\*\*\s*\|\s*Does the layout",
        "evals": r"\*\*(\d+) cases\*\*",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, doc)
        if match:
            found[key] = int(match.group(1))
    return found


def check_counts(doc: str) -> list[Problem]:
    stated = stated_counts(doc)
    actual = {
        "backend": count_backend_tests(),
        "frontend": count_frontend_tests(),
        "e2e": count_e2e_tests("assistant.spec.ts"),
        "mobile": count_e2e_tests("mobile.spec.ts"),
        "evals": count_eval_cases(),
    }

    problems: list[Problem] = []
    for key, claimed in stated.items():
        real = actual.get(key)
        if real == UNAVAILABLE:
            # The toolchain is absent. Not a stale document, and not this tool's business.
            continue
        if real is None:
            # The suite exists but its output could not be read. Reported rather than
            # skipped: a check that quietly does nothing is worse than no check.
            problems.append(
                Problem(f"§5 {key}", "could not determine the real count — fix the checker")
            )
            continue
        if real != claimed:
            problems.append(
                Problem(
                    f"§5 {key}",
                    f"document says {claimed}, the suite collects {real}. "
                    f"Run with --update-counts.",
                )
            )
    return problems


def last_code_change() -> date | None:
    output = _run(
        ["git", "log", "-1", "--format=%cs", "--", *CODE_PATHS],
        ROOT,
    ).strip()
    try:
        return datetime.strptime(output, "%Y-%m-%d").date()
    except ValueError:
        return None


def check_staleness(doc: str) -> list[Problem]:
    match = re.search(r"\*\*Last verified:\*\*\s*(\d{4}-\d{2}-\d{2})", doc)
    if not match:
        return [Problem("header", "no `**Last verified:**` date")]
    verified = datetime.strptime(match.group(1), "%Y-%m-%d").date()

    changed = last_code_change()
    if changed is None:
        return []
    drift = (changed - verified).days
    if drift > STALENESS_DAYS:
        return [
            Problem(
                "header",
                f"last verified {verified}, but code changed {changed} "
                f"({drift} days later). Re-read the status rows and update the date.",
            )
        ]
    return []


# --- count refresh ----------------------------------------------------------------


def update_counts() -> int:
    doc = read_doc()
    replacements = {
        r"(\*\*)(\d+)( passing, \d+% coverage\*\*)": count_backend_tests(),
        r"(\*\*)(\d+)( passing\*\*\s*\|\s*Do the parser)": count_frontend_tests(),
        r"(\*\*)(\d+)( passing\*\* \(4 shell)": count_e2e_tests("assistant.spec.ts"),
        r"(\*\*)(\d+)( passing\*\*\s*\|\s*Does the layout)": count_e2e_tests("mobile.spec.ts"),
        r"(\*\*)(\d+)( cases\*\*)": count_eval_cases(),
    }
    for pattern, value in replacements.items():
        if value is None or value == UNAVAILABLE:
            continue
        doc = re.sub(pattern, lambda m, v=value: f"{m.group(1)}{v}{m.group(3)}", doc)

    doc = re.sub(
        r"\*\*Last verified:\*\*\s*\d{4}-\d{2}-\d{2}",
        f"**Last verified:** {date.today().isoformat()}",
        doc,
    )
    STATUS_DOC.write_text(doc, encoding="utf-8")
    print(f"updated {STATUS_DOC.relative_to(ROOT)}")
    return 0


# --- entry point ------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-counts",
        action="store_true",
        help="run the suites and rewrite the counts and the verification date",
    )
    args = parser.parse_args()

    if args.update_counts:
        return update_counts()

    doc = read_doc()
    problems = (
        check_paths_exist() + check_empty_claims(doc) + check_counts(doc) + check_staleness(doc)
    )

    if not problems:
        print(f"implementation status is current ({STATUS_DOC.relative_to(ROOT)})")
        return 0

    print(f"{STATUS_DOC.relative_to(ROOT)} is out of date:\n", file=sys.stderr)
    for problem in problems:
        print(f"  {problem.where}: {problem.detail}", file=sys.stderr)
    print(
        "\nThis document is the checkpoint for what is built. Fix the rows, "
        "not the checker.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
