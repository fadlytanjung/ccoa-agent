---
description: Break an implementation plan into tracked tasks and start executing
argument-hint: <docs/plans/NN-slug.plan.md> [slice number]
---

Break down and execute: **$ARGUMENTS**

## Process

1. Read the plan. If a slice number was given, scope to that slice only; otherwise
   take the first slice that is not yet complete.
2. Create one task per row in the slice's table using `TaskCreate`. Set `addBlockedBy`
   to encode the `Depends on` column so the ordering is machine-visible.
3. Work the tasks in dependency order. Mark `in_progress` before starting and
   `completed` only when the change is written **and** its test passes.
4. After the last task in a slice, run the full gate before declaring the slice done:

```bash
cd backend  && uv run ruff check . && uv run mypy app && uv run pytest
cd frontend && npm run lint && npm run typecheck && npm run build
cd terraform && terraform fmt -check -recursive && terraform validate
```

## Rules

- **Do not mark a task complete on a failing test.** If blocked, leave it
  `in_progress` and create a new task describing the blocker.
- If implementing reveals the spec is wrong, stop and fix the spec first — then
  re-plan the affected steps. Code that contradicts an approved spec is a defect
  even when it works.
- Keep changes reviewable: one task, one focused diff. Do not opportunistically
  refactor unrelated code inside a task.
- Never weaken a test to make it pass.
