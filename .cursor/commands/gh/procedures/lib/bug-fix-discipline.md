---
name: bug-fix-discipline
description: Shared bug-fix execution rules for /gh-build (prove_it) and /gh-resolve-issues subagents. Scope, Prove-It TDD, simplify, verify, commit.
---

# Bug-fix discipline

Shared per-bug implementation loop for **Prove-It** mode (`build_hints.tdd_mode: prove_it` on `/gh-build`) and **each Bug subagent** on `/gh-resolve-issues`.

## Load (in order)

1. [build-discipline.md](build-discipline.md) — minimal change, scope binding
2. [gh-build-github-procedure.md](gh-build-github-procedure.md#phase-b--implement) — Phase B implement loop
3. [test-driven-development.md](test-driven-development.md#the-prove-it-pattern-bug-fixes) — Prove-It RED/GREEN
4. [code-simplification.md](code-simplification.md#simplification-process) — clarity pass before commit

**On verify/TDD failure:** [debugging-and-error-recovery.md](debugging-and-error-recovery.md#stop-the-line), [#triage-checklist](debugging-and-error-recovery.md#triage-checklist)

## Per-bug loop

| Step | Action |
|------|--------|
| Scope | Bug `scope_files` (Involved code) + task/story issue as outer boundary |
| RED | Failing regression test that reproduces the bug |
| GREEN | Minimal fix; test passes |
| Simplify | Scoped clarity pass on changed files only |
| Verify | Bug/task `verify_cmd` + affected tests |
| Document | Add `## Tests` on Bug issue when tests were added |
| Commit | `git commit` + `git push` on active branch |

Do **not** skip RED confirmation. Add regression tests to the suite when unit/integration tests can catch recurrence.
