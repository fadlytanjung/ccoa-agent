---
description: Audit implemented code against its specification and report drift
argument-hint: <docs/NN-slug.md>
---

Audit the implementation against the spec: **$ARGUMENTS**

## Process

1. Read the spec in full.
2. Locate every piece of code that implements it. Search — do not assume file names.
3. For each normative statement in the spec (anything with *must*, *shall*, a pinned
   value, or a typed signature), determine whether the code actually does it.
4. Run the tests and the gate commands; capture real output, do not predict it.

## Report

Group findings into exactly these buckets:

| Bucket | Meaning |
|---|---|
| **Conformant** | Spec statement is implemented and covered by a test |
| **Untested** | Implemented, but nothing would catch a regression |
| **Drift** | Code and spec disagree — say which one appears to be right |
| **Missing** | Spec requires it, code does not do it |
| **Undocumented** | Code does something material the spec never mentions |

For each non-conformant finding give `file:line`, quote the spec line, and state the
concrete failure — the input or condition under which the behaviour diverges.

## Rules

- Report faithfully. If the suite fails, show the failure output; do not summarise it
  as "some tests failing".
- **Drift is resolved by a human decision**, not unilaterally. Propose which side to
  change and why, then wait — do not rewrite the spec to match the code, or vice
  versa, without being asked.
- Verify security claims against reality, not against intent: if the spec says the
  Gemini key comes from Secrets Manager, confirm no code path reads it from an env var
  baked at build time, and confirm it is absent from the image and task definition.
- Check the constitution too — a change can conform to its own spec and still violate
  `docs/00-constitution.md`.
