---
name: build-discipline
description: Minimal change and scope discipline for /build and /gh-build execution. Use when implementing tasks — smallest diff, existing patterns, TDD binding.
---

# Build discipline (execution)

Shared execution rules for [/build](../lib/build.md) and [/gh-build](../../gh-build.md). Planning-side scoping lives in [plan-minimal-change.md](plan-minimal-change.md).

<a id="simplicity-first-rule-0"></a>

## Simplicity first (Rule 0)

Before writing code: **what is the simplest thing that could work?**

After writing, check: fewer lines without losing clarity? Abstractions earning their cost? Building for current task, not hypothetical futures?

Three similar lines beat a premature abstraction. Implement the naive correct version first; optimize after tests prove correctness.

## Minimal change

Implement the **smallest change** that satisfies the task. Extend **existing patterns** — same naming, layering, error handling, and call style as neighboring code and any `## Patterns` / **Existing Patterns to Follow** on the task.

**Do not** (unless the task or user explicitly requested):

- Rewrite working code to a different pattern “because it’s cleaner”
- Introduce abstractions, base classes, or shared utilities for one call site
- Rename, reformat, or reorganize unrelated files “while you’re here”
- Modernize syntax or imports in files you only read for context
- Skip the failing-test step or implement before a test exists (except pure config/docs with no behavioral impact)

<a id="scope-discipline-rule-05"></a>

## Scope discipline (Rule 0.5)

Touch only what the task requires.

For `/gh-build`: `## Scope` files + test files from `## Tests` (+ bootstrapped harness paths when `test_harness.bootstrapped` is true — see [gh-build-github-procedure.md](procedures/pipeline/gh-build-github-procedure.md#harness-path-allowance)).

Do **not**:

- “Clean up” code adjacent to your change
- Refactor imports in files you're not modifying
- Add features not in the spec because they “seem useful”
- Modernize syntax in files you're only reading

If you notice something worth improving outside scope, note it — don't fix it:

```text
NOTICED BUT NOT TOUCHING:
- src/utils/format.ts has an unused import (unrelated to this task)
→ Want me to create a task for this?
```

## TDD binding (`/gh-build`)

Use `build_hints.tdd_mode` from context JSON:

| Mode | When | Load |
|------|------|------|
| `red_green_refactor` | Feature / new behavior | [TDD Cycle](test-driven-development.md#the-tdd-cycle) + [Git checkpoints](test-driven-development.md#git-checkpoint-discipline) |
| `prove_it` | Bug fix | [bug-fix-discipline.md](bug-fix-discipline.md) |

For every increment: **RED → GREEN → REFACTOR**. After each GREEN increment, run `verify` (not only at end). Do not commit until scripted verify and gates pass.

**Browser/UI** — when `build_hints.browser_verify_required` is true, load [browser-testing-with-devtools.md](browser-testing-with-devtools.md#devtools-workflow) and [#security-boundaries](browser-testing-with-devtools.md#security-boundaries); verify with Chrome DevTools MCP or cursor-ide-browser when available.

On failure, load [debugging-and-error-recovery.md](debugging-and-error-recovery.md#stop-the-line) and [#triage-checklist](debugging-and-error-recovery.md#triage-checklist).

**AC gate (before commit):** every cited `AC-*` scenario from the parent story is satisfied by implementation and tests.
