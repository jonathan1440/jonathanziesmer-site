---
name: gh-resolve-issues
description: Resolve Bug sub-issues on Composer under a GitHub task or user-story issue — parallel subagent fixes, Prove-It tests, merge to branch, update existing PR. Use when a task or story issue has Bug sub-issues from gh-review and an open linked PR needs fixes without new PRs.
---

# gh-resolve-issues

GitHub-native bug resolution for a **task issue** or **user story issue** with **Bug** (or review-finding **Task**) sub-issues from `/gh-review`.

## Model (Composer)

This workflow **must** run on Composer (`composer-2.5`).

| Session | Action |
| --- | --- |
| Already Composer, or you **are** the `gh-resolve-issues` agent | Proceed with the checklist below |
| Auto / frontier / anything else | Spawn Task `subagent_type: gh-resolve-issues` (fallback: `generalPurpose` + `model: composer-2.5`), pass the issue URL, return its result — **do not resolve in the parent session** |

Per-bug fix subagents must also use **`model: composer-2.5`**. Auto-workflow already pins resolve jobs to `composer-2.5` via `spawn.models`.

**Phase 5 PR policy:** each review-generated finding gets its **own branch and PR** (`Closes owner/repo#N`) for tracking/visibility. After gates pass, the agent **may merge finding PRs only**. Never merge the parent Spec, User Story, or normal Task PR — those stay human-merge only. Parent Status → Ready to ship only after finding PRs are merged and the parent PR remains open for human review.

**You MUST run `gh-resolve-publish.py` yourself** via Shell. Do **not** hand commands to the user. On script failure: diagnose, fix inputs, retry.

**Do not duplicate bash, JSON, or procedure detail here.** → [gh-resolve-issues-github-procedure.md](procedures/pipeline/gh-resolve-issues-github-procedure.md)

## Load (conditional)

**Always:** [gh-resolve-issues-github-procedure.md](procedures/pipeline/gh-resolve-issues-github-procedure.md)

**Per-bug subagents:** [bug-fix-discipline.md](procedures/lib/bug-fix-discipline.md) + [gh-resolve-parallel-subagents.md](procedures/pipeline/gh-resolve-parallel-subagents.md)

**Before parallel dispatch:** [dispatching-parallel-agents.md](procedures/lib/dispatching-parallel-agents.md)

**On verify/TDD failure:** [debugging-and-error-recovery.md](procedures/lib/debugging-and-error-recovery.md#stop-the-line), [#triage-checklist](procedures/lib/debugging-and-error-recovery.md#triage-checklist)

## Checklist

Use `--state-dir` pattern `$STATE=/tmp/gh-resolve-<issue#>` ([procedure §State directory](procedures/pipeline/gh-resolve-issues-github-procedure.md#state-directory)).

1. **preflight** — once per session ([procedure §Prerequisites](procedures/pipeline/gh-resolve-issues-github-procedure.md#prerequisites))
2. **context** or **start** — parse input issue + Bug sub-issues; Status → **In-progress**; stop if `resolve_status: "complete"` or no open bugs ([procedure §Phase 1](procedures/pipeline/gh-resolve-issues-github-procedure.md#phase-1--context--start))
3. **Blocker gate** — stop if `blocker_gate.open_blockers` non-empty unless user overrides
4. **checkout-task** — never main/spec/new branch ([procedure §Phase 2](procedures/pipeline/gh-resolve-issues-github-procedure.md#phase-2--checkout))
5. **create-bug-branch** for each bug sequentially, then **parallel subagents** — one Bug each ([procedure §Phase 3](procedures/pipeline/gh-resolve-issues-github-procedure.md#phase-3--bug-branches--parallel-fixes), [parallel subagents](procedures/pipeline/gh-resolve-parallel-subagents.md))
6. **record-bug** after each subagent returns — local context only; GitHub issues stay open
7. **merge-bugs** → **gates --require-verify** → **finish** — closes Bug sub-issues and sets Status → **Ready to ship** on project board; check `status_update.ok` ([procedure §Phase 4](procedures/pipeline/gh-resolve-issues-github-procedure.md#phase-4--merge-gates--publish))
8. **Present output** — `## INCOMPLETE` if any gate failed

Debug: individual subcommands — [procedure §Reference](procedures/pipeline/gh-resolve-issues-github-procedure.md#reference).

## When to use

- **Task issue** or **user story issue** has open **Bug** sub-issues from `/gh-review`
- Development branch and linked PR already exist (from `/gh-build` or prior work)
- User wants all bugs fixed on the branch and the **existing PR updated**
- Examples:
  - after `/gh-review` on a **task issue**, run `/gh-resolve-issues` on that task
  - after `/gh-review` on a **user story** (bugs filed as story sub-issues), run on the story issue (e.g. `US-01` #2)

**When NOT to use:**

| Situation | Use instead |
|-----------|-------------|
| No Bug sub-issues yet | `/gh-review` |
| No task branch / no PR yet | `/gh-build` |
| Local triage markdown (no GitHub bugs) | `/research-issues` |
| Single task implementation (no bugs) | `/gh-build` |

## Inputs

| Input | Required | Example |
|-------|----------|---------|
| Task or story issue | Yes | URL or `the-trail-gang/knowledge-graph#2` (story) or `…#21` (task) |
| Finding kind | No | `--finding-kind task` when RR findings are GitHub **Task** sub-issues (default: `bug`) |
| Linked PR override | No | `--pr https://github.com/org/repo/pull/115` when cross-repo issue/PR linking fails |

## Present output

If `resolve_status` is `"complete"`, report prior run already finished (list `closed_bugs` URLs) — do not dispatch fixes.

If any completion gate failed, lead with **`## INCOMPLETE`** and list open bug issue URLs.

| Field | Value |
|-------|--------|
| Issue | task or story issue URL |
| Branch | development branch (merged) |
| Bugs fixed | finding IDs + commit SHAs |
| Tests | regression tests added per bug |
| PR | updated linked PR URL |
| Bug issues | closed sub-issue URLs |
| Verify | task verify + full suite (+ browser if UI) — `verify` / `gates` JSON in `$STATE` |
| Status | **Ready to ship** — `status_update.ok` in finish output |
| Parent issue | **left open** (task or story) |

## Critical rules (orchestration)

- **Composer** — resolve only on Composer (see [Model](#model-composer)); bug-fix Tasks use `model: composer-2.5`
- **No new PRs** — update `linked_pr` test plan only
- **`record-bug` ≠ issue closure** — `close-bugs` runs only after gates pass
- **Parent task/story issue stays open**
- **Parallel subagents** — one Bug each; parent integrates merges and runs scripted `gates`/`verify`
- **Scripted gates before finish** — `finish` requires green gates by default; iterate on task branch until green
- **Durable surprises** — propose `AGENTS.md` pitfalls via `/write-agents-contract` pitfall mode; never edit the contract silently

Re-run behavior, per-bug discipline, mechanical red flags, and post-run checklist → [procedure §Re-run](procedures/pipeline/gh-resolve-issues-github-procedure.md#re-run-behavior), [bug-fix-discipline](procedures/lib/bug-fix-discipline.md), [§Red flags](procedures/pipeline/gh-resolve-issues-github-procedure.md#red-flags), [§Verification](procedures/pipeline/gh-resolve-issues-github-procedure.md#verification)

## Workflow chain

```text
/gh-build → /gh-review → /gh-resolve-issues → PR updated → human review → merge
```

After `/gh-resolve-issues` completes, the PR is ready for the human review-and-merge loop described in [README §Manual review and merge](README.md#manual-review-and-merge). Merging the PR closes the issue, which triggers the promotion check — when it was the last open sub-issue, the parent story/spec PR opens automatically ([README §Promotion](README.md#promotion)). For spec-level PRs, also see [README §Post-merge and release](README.md#post-merge-and-release) before closing the spec issue.

See also [gh-review.md](gh-review.md) and [gh-build.md](gh-build.md).
