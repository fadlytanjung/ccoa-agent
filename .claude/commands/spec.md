---
description: Author or revise a numbered specification in docs/ for a feature
argument-hint: <feature name or docs/NN-slug.md>
---

Author or revise the specification for: **$ARGUMENTS**

## Before writing

1. Read `docs/00-constitution.md` — the spec must not violate it.
2. Read `docs/01-requirements-traceability.md` and identify which `REQ-*` IDs this
   spec satisfies. If the feature maps to no requirement, stop and ask whether it is
   in scope.
3. Read any spec this one depends on (check `docs/README.md` for the dependency order).
4. If revising, read the existing file in full before editing.

## Structure every spec follows

```markdown
# NN — Title

> **Status:** Draft | Under review | Approved
> **Satisfies:** REQ-001, REQ-004
> **Depends on:** docs/03-architecture.md

## 1. Purpose
One paragraph: what this component is for and what it is not.

## 2. Scope
In scope / out of scope, as two explicit lists.

## 3. Design
The substance. Diagrams as mermaid. Interfaces as typed signatures.

## 4. Decisions and tradeoffs
Each meaningful choice, the alternatives, and why this one. Link to an ADR
in docs/adr/ when the decision is architectural and reversible only at cost.

## 5. Failure modes
What breaks, how it is detected, what happens next.

## 6. Open questions
Anything genuinely undecided. Empty list is a valid answer.
```

## Rules

- **Be specific enough to implement from.** "Validate the input" is not a spec;
  "reject `customer_id` not matching `^CUST-[0-9]{6}$` with HTTP 422" is.
- **Pin real values.** Exact model IDs, package versions, port numbers, IAM actions,
  table names. Never write `<some model>` or "the latest version".
- **State the tradeoff honestly.** A documented weakness beats
  an undocumented one. If SQLite-on-EFS caps us at one writer, say so in the spec.
- **No invented facts.** If you need an AWS price, a quota, or an API signature you
  are not certain of, verify it (`aws` CLI, PyPI, official docs) before writing it down.
  Mark anything unverified as `[UNVERIFIED]` rather than asserting it.
- Cross-link sibling specs by relative path so the doc set stays navigable.

After writing, update `docs/README.md` if the reading order or status changed.
