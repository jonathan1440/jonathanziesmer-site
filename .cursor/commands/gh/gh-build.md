---
name: gh-build
description: Implement one GitHub task issue on Composer — In-progress status, task-branch commit, PR to parent branch, Review / QA
---

# gh-build

GitHub-native implementation for a **single task sub-issue** from `/gh-plan`. Issue-driven scope, branch, tests, and traceability.

## Model (Composer)

This workflow **must** run on Composer (`composer-2.5`).

| Session | Action |
| --- | --- |
| Already Composer, or you **are** the `gh-build` agent | Proceed with the checklist below |
| Auto / frontier / anything else | Spawn Task `subagent_type: gh-build` (fallback: `generalPurpose` + `model: composer-2.5`), pass the task issue URL, return its result — **do not implement in the parent session** |

Auto-workflow already pins build jobs to `composer-2.5` via `spawn.models`.

**You MUST run `gh-build-publish.py` yourself** via Shell for parse, status, branch, verify, gates, commit, PR, and project updates. Do **not** hand commands to the user. On script failure: diagnose, fix inputs, retry.

**Do not duplicate bash, JSON, or procedure detail here.** → [gh-build-github-procedure.md](procedures/pipeline/gh-build-github-procedure.md)

## Load (conditional)

**Always:** [gh-build-github-procedure.md](procedures/pipeline/gh-build-github-procedure.md)

**Phase B — implement:** per `build_hints.tdd_mode` (see build-discipline §TDD binding)

- `red_green_refactor` — [build-discipline.md](procedures/lib/build-discipline.md) + [TDD Cycle](procedures/lib/test-driven-development.md#the-tdd-cycle)
- `prove_it` — [bug-fix-discipline.md](procedures/lib/bug-fix-discipline.md)

**Phase B — when `build_hints.browser_verify_required`:** [browser-testing-with-devtools.md](procedures/lib/browser-testing-with-devtools.md#devtools-workflow), [#security-boundaries](procedures/lib/browser-testing-with-devtools.md#security-boundaries)

**Phase C — simplify:** [code-simplification.md](procedures/lib/code-simplification.md#scope), [#simplification-process](procedures/lib/code-simplification.md#simplification-process)

**On verify/TDD failure:** [debugging-and-error-recovery.md](procedures/lib/debugging-and-error-recovery.md#stop-the-line), [#triage-checklist](procedures/lib/debugging-and-error-recovery.md#triage-checklist)

## Checklist

Use `--state-dir /tmp/gh-build-<issue#>` on every scripted step ([procedure §State directory](procedures/pipeline/gh-build-github-procedure.md#state-directory)).

1. **preflight** — once per session ([procedure §Prerequisites](procedures/pipeline/gh-build-github-procedure.md#prerequisites))
2. **prepare --sync-story** — parse task, Status → **In-progress**, checkout task branch (add `--worktree` to work this task in its own linked git worktree instead of in place — see [procedure §Worktree mode](procedures/pipeline/gh-build-github-procedure.md#worktree-mode--running-tasks-in-parallel)); stop on missing `## Scope` / `## Tests` or open blockers; read `build_hints`, `ac_ids`, `parent_branch` from `context.json`. Then propagate **In progress** to the parent story/spec (outline §5.3): `python3 .cursor/commands/_scripts/gh/gh-promote.py on-build --issue <task>` — see [README §Promotion](README.md#promotion)
3. **Implement** — TDD per `build_hints.tdd_mode`; [build-discipline](procedures/lib/build-discipline.md); run `verify` after each GREEN increment
4. **Simplify** — clarity pass on task changes only; re-run `verify`
5. **verify** — loop until exit 0 ([procedure §Verify loop](procedures/pipeline/gh-build-github-procedure.md#verify-loop-rules)); after 3 iterations on the same failure class, comment a summary on the task issue, @-mention the story owner, and stop (blocker)
6. **AC gate** — all cited `AC-*` satisfied (agent judgment)
7. **finalize --ac-attested** — gates + commit + PR + Review/QA + report; check `pr.url`, `status_update.ok`; leave task issue **open**. Task PRs squash-merge into the story branch — see [README §Merge strategy](README.md#merge-strategy)

Optional read-only: `context` before `prepare` when inspecting scope without status mutation ([procedure §Phase A](procedures/pipeline/gh-build-github-procedure.md#phase-a--prepare)).

Debug: individual subcommands (`start`, `checkout`, `gates`, `commit-push`, `finish`, `report`, `cleanup-worktree`) — [procedure §Reference](procedures/pipeline/gh-build-github-procedure.md#reference).

## When to use

- After `/gh-plan` `finish-plan` — one task issue at a time
- Any GitHub task issue with `## Scope` and `## Tests` (`## Development branch` optional — created when missing)
- Example: `https://github.com/run-rhino/finish-photos-ui/issues/12`
- **Standalone bug issue, no story/spec** — a bare Bug issue with `## Repository`, `## Scope`, and `## Tests` but no `## Traceability` builds directly against the repo default branch: branch is `bug/<n>-slug`, PR targets the default branch, and `--sync-story` is skipped (there's no parent branch to sync from). No spec/story issues needed.

**When NOT to use:** Local `plan.md` tasks → [/build](procedures/lib/build.md). Story-level planning → [/gh-plan](gh-plan.md).

## Inputs

| Input | Required | Example |
|-------|----------|---------|
| Task issue | Yes | URL or `run-rhino/finish-photos-ui#12` |

## Present output

| Field | Source |
|-------|--------|
| Task / Story / Branch / Commit / PR / Verify / Gates | `report.json` in `--state-dir` |
| AC | agent attestation |
| TDD / Simplify | agent attestation |
| Browser | when `build_hints.browser_verify_required` |

## Critical rules (orchestration)

- **Composer** — implement only on Composer (see [Model](#model-composer)); delegate via `gh-build` agent when parent is not Composer
- **Status In-progress first** — confirm `status_update.ok` in prepare output
- **Scripted verify loop + gates** — tiers 1–4 + task verify before finalize/commit, stopping at the first failing tier; see [procedure §Verify loop](procedures/pipeline/gh-build-github-procedure.md#verify-loop-rules)
- **AC gate before finalize** — use `--ac-attested` only after confirming all cited AC-*
- **No nested implementation subagents** — you are the worker; do not spawn further build agents
- **Run gh-build-publish.py** — do not hand GitHub/git commands to the user
- **Durable surprises** — if you learn a pitfall the next agent would miss and it belongs in `AGENTS.md`, propose it via `/write-agents-contract` **pitfall mode** (never edit `AGENTS.md` silently)

Mechanical red flags and post-run checklist → [procedure §Red flags](procedures/pipeline/gh-build-github-procedure.md#red-flags), [§Verification](procedures/pipeline/gh-build-github-procedure.md#verification)

## Workflow chain

```text
/gh-spec → /gh-plan → /gh-build (per task) → PR (task → story) → merge story → spec
```

Each command is invoked separately.
