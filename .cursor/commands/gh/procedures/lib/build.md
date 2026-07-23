---
name: build
description: Implement the next task incrementally — build, test, verify, commit
---

Load [build-discipline.md](build-discipline.md) together with [test-driven-development.md](test-driven-development.md#the-tdd-cycle) and [#git-checkpoint-discipline](test-driven-development.md#git-checkpoint-discipline).

For multi-slice planning beyond a single task, see [incremental-implementation.md](incremental-implementation.md).

Pick the next pending task from the plan. For each task:

1. Read the task's acceptance criteria
2. Load relevant context — find the **nearest existing example** of the same kind of change (same layer, module, or feature) and mirror its structure; if the plan lists **Existing Patterns to Follow**, treat those as binding
3. Write a failing test for the expected behavior (RED)
4. Implement the **minimum** code to pass the test (GREEN), using the pre-existing pattern — not a new one
5. Run the full test suite to check for regressions
6. Run the build to verify compilation
7. Commit with a descriptive message
8. Mark the task complete and move to the next one

If any step fails, load [debugging-and-error-recovery.md](debugging-and-error-recovery.md#stop-the-line) and [#triage-checklist](debugging-and-error-recovery.md#triage-checklist).
