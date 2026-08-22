---
description: Turn an approved spec into a concrete implementation plan
argument-hint: <docs/NN-slug.md>
---

Produce an implementation plan for the spec: **$ARGUMENTS**

## Preconditions

Refuse to plan if the spec's `Status:` is not `Approved`. Say which spec is blocking
and stop — planning against a moving spec wastes the work.

## Process

1. Read the spec in full, plus every spec it declares under `Depends on:`.
2. Inventory what already exists in the repo that this can reuse. Do not plan to build
   something the codebase already has — search first.
3. Identify the **thinnest vertical slice** that proves the design works end to end,
   and plan that first. Breadth after depth.

## Output

Write the plan to `docs/plans/NN-slug.plan.md`:

```markdown
# Implementation plan — <spec title>

## Slice 1: <name>  (proves: <what risk this retires>)
| # | Change | File(s) | Depends on |
|---|--------|---------|------------|
| 1 | ...    | ...     | —          |

**Done when:** <observable, testable condition>

## Slice 2: ...
```

## Rules

- Every step names the actual files it touches. "Update the backend" is not a step.
- Every slice ends in a state where the test suite passes and the app runs. No slice
  may leave the repo broken.
- Call out the steps that need a real Gemini API key or real AWS credentials — these
  cannot run in CI without secrets and need explicit handling.
- Flag any step where the spec is ambiguous rather than silently choosing. Ambiguity
  found at plan time is cheap; found at implement time it is not.
- Estimate nothing in hours. Order by dependency, not by guessed duration.
