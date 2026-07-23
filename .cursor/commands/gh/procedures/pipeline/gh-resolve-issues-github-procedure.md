# gh-resolve-issues — GitHub publish procedure

Operational contract for `/gh-resolve-issues`. Load with [gh-resolve-issues.md](../../gh-resolve-issues.md).

Resolves **Bug** (and review-finding **Task**) sub-issues under a **task issue** or **user story issue**.

**Phase 5:** each finding gets its own branch + PR. Agents may merge those finding PRs after gates. Parent Spec / User Story / normal Task PRs remain human-merge only. Use `.cursor/commands/_scripts/auto/merge_policy.py` (`can_agent_merge_pr` / `assert_agent_may_merge`) before any `gh pr merge`.

Legacy path (merge bug branches into the parent development branch and update the linked parent PR) remains available for in-flight runs, but **new** resolve work should open per-finding PRs.

## Contents

1. [Prerequisites](#prerequisites)
2. [State directory](#state-directory)
3. [Phase 0 — Preflight](#phase-0--preflight)
4. [Phase 1 — Context + start](#phase-1--context--start)
5. [Phase 2 — Checkout](#phase-2--checkout)
6. [Phase 3 — Bug branches + parallel fixes](#phase-3--bug-branches--parallel-fixes)
7. [Phase 4 — Merge, gates, publish](#phase-4--merge-gates--publish)
8. [Re-run behavior](#re-run-behavior)
9. [Issue body contracts](#issue-body-contracts)
10. [Reference](#reference)
11. [Red flags](#red-flags)
12. [Verification](#verification)

---

## Prerequisites

```bash
gh --version          # ≥ 2.40 recommended
gh auth status        # repo + project scopes
python3 .cursor/commands/_scripts/gh/gh-resolve-publish.py preflight
python3 .cursor/commands/_scripts/gh/gh-build-publish.py preflight
```

- **Task issue** or **user story issue** has open **Bug** sub-issues (typically from `/gh-review` `sync-bugs`)
- Input issue has a linked **development branch** (`task/US-*` or `user-story/US-*`)
- An **open PR** linked to the input issue exists (head = development branch)
- Local clone of the code repo (`## Repository` or `## Repositories touched`) with `origin` pointing at the code repo

**Story issues:** `/gh-review` may file Bug sub-issues directly under the user story (not under a task). The script detects `## User story` / `## Acceptance scenarios` and resolves the branch from `## Development branches` or linked `user-story/*` branch.

---

## State directory

Use a predictable directory per input issue (mirrors `/gh-build`):

```bash
STATE=/tmp/gh-resolve-21   # use input issue number
```

| File | Written by |
|------|------------|
| `context.json` | `context`, `start`, `checkout-task`, `create-bug-branch`, `record-bug`, `merge-bugs` |
| `gates.json` | `gates`, `finish` |
| `verify.json` | `verify` |
| `finish.json` | `finish` |

Pass `-o "$STATE/context.json"` (or `--input "$STATE/context.json"`) on every scripted step. Reload context from `-o` after each step.

> **Convention note:** `gh-resolve-publish.py` uses explicit `-o`/`--input` flags per step rather than the `--state-dir` shorthand used by `gh-build-publish.py`. The effect is the same — a shared JSON file accumulates state — but you must pass the path explicitly on every call rather than letting the script infer filenames from a directory.

Example (issue #21):

```bash
STATE=/tmp/gh-resolve-21
python3 .cursor/commands/_scripts/gh/gh-resolve-publish.py context \
  --issue run-rhino/finish-photos-ui#21 -o "$STATE/context.json"
python3 .cursor/commands/_scripts/gh/gh-resolve-publish.py start \
  --issue run-rhino/finish-photos-ui#21 -o "$STATE/context.json"
python3 .cursor/commands/_scripts/gh/gh-resolve-publish.py checkout-task \
  --input "$STATE/context.json" -o "$STATE/context.json"
# … parallel subagent fixes per Bug …
python3 .cursor/commands/_scripts/gh/gh-resolve-publish.py merge-bugs \
  --input "$STATE/context.json" -o "$STATE/context.json"
python3 .cursor/commands/_scripts/gh/gh-resolve-publish.py gates \
  --input "$STATE/context.json" --require-verify \
  -o "$STATE/gates.json"
python3 .cursor/commands/_scripts/gh/gh-resolve-publish.py finish \
  --input "$STATE/context.json" \
  --verify-result "$STATE/gates.json" \
  -o "$STATE/finish.json"
```

On script failure: diagnose, fix inputs, retry.

---

## Phase 0 — Preflight

Run once per session (see [Prerequisites](#prerequisites)).

---

## Phase 1 — Context + start

### Context (read-only inspect)

```bash
python3 .cursor/commands/_scripts/gh/gh-resolve-publish.py context \
  --issue owner/repo#12 [--pr https://github.com/org/repo/pull/115] \
  [--finding-kind bug|task] \
  -o "$STATE/context.json"
```

**Finding kind:** Default `--finding-kind bug` matches GitHub Bug sub-issues from `/gh-review sync-bugs`. Use `--finding-kind task` when RR findings were filed as **Task** sub-issues (same `[RR-NN]` title/body contract).

Confirm `bugs[]` is non-empty, `task_branch.branch` is set, `linked_pr` is present (or pass `--pr`).

**Gates — stop if:**

| Condition | Action |
|-----------|--------|
| No open Bug sub-issues and no closed RR sub-issues | Run `/gh-review` first |
| `resolve_status: "complete"` | Report success; list `closed_bugs` URLs; do not dispatch fixes |
| No development branch | Link `user-story/*` or `task/*` via `gh issue develop` or `## Development branches` |
| No linked PR | Try `--pr URL` or confirm PR references input issue / matches branch head |

**PR discovery order:** (1) GitHub `linked:issue-N` on input repo → (2) open PR with matching head branch → (3) open PR body references issue number → (4) `--pr` override.

### Start (default — sets In-progress)

```bash
python3 .cursor/commands/_scripts/gh/gh-resolve-publish.py start \
  --issue owner/repo#12 [--pr URL] -o "$STATE/context.json"
```

Equivalent to `context` + set input issue Status **In-progress**. Stop if `blocker_gate.open_blockers` is non-empty unless user overrides.

Read `story_issue`, `ac_ids`, `ac_scenarios` from context for regression context (same as gh-build).

Exemplar: [gh-resolve.example.context.json](../../examples/gh-resolve.example.context.json).

---

## Phase 2 — Checkout

```bash
python3 .cursor/commands/_scripts/gh/gh-resolve-publish.py checkout-task \
  --input "$STATE/context.json" -o "$STATE/context.json"
```

Confirm `checkout.current_branch` equals `task_branch.branch`.

**Never** implement on `main`, `spec/<slug>`, or a new branch. Use the branch linked to the **input issue** (task branch or `user-story/*` story branch).

**If a `/gh-build --worktree` session for this task is still open:** `checkout-task` checks out `task_branch` directly in whatever `local_repo_path` it discovers, which fails (`fatal: '<branch>' is already checked out at '<worktree path>'`) if that branch is currently checked out in a linked worktree elsewhere. Pass `--repo-path <that worktree_path>` explicitly instead of relying on auto-discovery — auto-discovery has no way to know the build worktree exists.

---

## Phase 3 — Bug branches + parallel fixes

**Before dispatch** — create all bug branches (parent, sequential). Pass `--worktree` so each bug gets its own linked git worktree — required for subagents to safely work in parallel (see [gh-resolve-parallel-subagents.md](gh-resolve-parallel-subagents.md)):

```bash
for id in RR-01 RR-02; do
  python3 .cursor/commands/_scripts/gh/gh-resolve-publish.py create-bug-branch \
    --input "$STATE/context.json" --bug "$id" --worktree -o "$STATE/context.json"
done
```

Each bug's entry in `context.json` now has a `worktree_path` — pass it as `--repo-path` in that bug's subagent prompt.

**Then** dispatch one subagent per bug in parallel. Full contract → [gh-resolve-parallel-subagents.md](gh-resolve-parallel-subagents.md).

Each subagent loads [bug-fix-discipline.md](../lib/bug-fix-discipline.md). Parent runs `record-bug` after each returns — does **not** close GitHub issues.

---

## Phase 4 — Merge, gates, publish

Run on task/story branch **after** all bugs are recorded via `record-bug`.

```bash
python3 .cursor/commands/_scripts/gh/gh-resolve-publish.py merge-bugs \
  --input "$STATE/context.json" -o "$STATE/context.json"
python3 .cursor/commands/_scripts/gh/gh-resolve-publish.py gates \
  --input "$STATE/context.json" --require-verify \
  -o "$STATE/gates.json"
python3 .cursor/commands/_scripts/gh/gh-resolve-publish.py finish \
  --input "$STATE/context.json" \
  --verify-result "$STATE/gates.json" \
  -o "$STATE/finish.json"
```

`finish` runs `merge-bugs` (skips already-merged), **gates** (default `--require-verify`), then `update-pr`, `close-bugs`, and finally sets Status → **Ready to ship** on the project board. Check `status_update.ok` in finish output. When gates fail, `finish` exits non-zero and leaves bugs open — fix on task branch, re-run gates, then `finish`.

If bugs were built with `create-bug-branch --worktree`, remove each bug's worktree once its branch is confirmed merged (after `finish` succeeds):

```bash
for id in RR-01 RR-02; do
  python3 .cursor/commands/_scripts/gh/gh-build-publish.py cleanup-worktree \
    --repo-path "$MAIN_REPO_PATH" --worktree-path "$WORKTREE_ROOT/bug-$id-slug"
done
```

**Do not** call `gh-build-publish.py open-pr` or create new PRs.

On merge conflict, `merge-bugs` writes `merge.failed` with conflict files and does **not** push. Resolve on task branch, commit, re-run `merge-bugs` (already-merged branches are skipped).

### Completion gates

```text
GATE all_bugs_recorded → GATE merge complete → GATE verify.ok → GATE close-bugs
```

| Gate | Check |
|------|-------|
| `all_bugs_recorded` | Every bug in `bugs[]` has `status: fixed` and a commit SHA |
| `all_bugs_merged` | Every bug branch is an ancestor of task branch HEAD |
| `linked_pr` | Open PR resolved (auto or `--pr` override) |
| `verify` | Tier 1–2 scripts + task verify green (shared `run_verify` from gh-build-publish; uses `uv run` when `uv.lock` exists) |
| `close-bugs` | All Bug sub-issues closed on GitHub |

If any gate fails, present output under **`## INCOMPLETE`** with open bug URLs — never list bugs as fixed unless their GitHub issues are closed.

---

## Re-run behavior

Safe to run `/gh-resolve-issues` again on the same issue:

| Situation | Script behavior |
|-----------|-----------------|
| All Bug sub-issues already closed | `context` / `start` return `resolve_status: "complete"` — present as done; `finish` is a no-op |
| Partial run (fixes pushed, context stale) | `context` / `finish` call `hydrate_bugs_from_git` when `local_repo_path` is set — infers `fixed` from merged `bug/*` branches |
| Bug branch already exists on remote | `create-bug-branch` checks out `origin/<branch>` instead of recreating |
| Bug branch already merged | `merge-bugs` skips with `skipped: true` |
| Bug issue already closed | `close-bugs` skips without error |
| Same commit re-recorded | `record-bug` returns `skipped: true` |
| PR body already has fix block | `update-pr` replaces the `## Bug fixes resolved` section |

---

## Issue body contracts

### Task issue

Same as `/gh-build` — see [gh-build-github-procedure §Phase A](gh-build-github-procedure.md#phase-a--prepare). Required: `## Task`, `## Repository`, `## Scope`, `## Tests`. Optional: `## Development branch`, `## Traceability` (omit for a standalone bug issue with no parent story — builds against the repo default branch instead).

### User story issue

When `/gh-review` files Bug sub-issues on the story (not a task):

| Section | Required | Use |
|---------|----------|-----|
| Title `US-XX: …` | Yes | Story id for branch/manifest lookup |
| `## User story` | Yes | Detect story mode (with `## Acceptance scenarios`) |
| `## Repositories touched` | Yes | Code repo for local checkout |
| `## Development branches` | Yes | `user-story/US-XX-*` branch per repo |
| `## Acceptance scenarios` | Preferred | AC ids for regression context |

Scope and verify come from each Bug's `## Involved code` and tests; default verify is `pytest -q`.

### Bug issue

From `/gh-review` `sync-bugs`:

| Section | Required | Use |
|---------|----------|-----|
| `## Finding` / title `[RR-NN]` | Yes | Identity |
| `## Involved code` | Preferred | Primary scope (Path column) |
| `## Recommendation` | Yes | Fix direction |
| `## Reproduction` | No | Prove-It repro steps |
| `## Tests` | No | Agent adds when missing after writing regression tests |

---

## Reference

### Scripts

Path: `.cursor/commands/_scripts/gh/gh-resolve-publish.py`

| Command | Purpose |
|---------|---------|
| `preflight` | gh auth + sub-issue support |
| `context --issue REF [--pr URL] [-o PATH]` | Parse task or story issue + open RR sub-issues + linked PR → JSON |
| `start --issue REF [--pr URL] [-o PATH]` | `context` + set task Status **In-progress** |
| `checkout-task --input CONTEXT [-o PATH] [--repo-path PATH]` | Checkout task issue branch locally |
| `create-bug-branch --input CONTEXT --bug RR-01 [-o PATH]` | Create `bug/rr-01-<slug>` from task branch |
| `commit-push --input CONTEXT --bug RR-01 [-o PATH]` | Commit scope + test files on bug branch |
| `merge-bugs --input CONTEXT [-o PATH]` | Merge all fixed bug branches → task branch (skips already-merged) |
| `gates --input CONTEXT [--require-verify] [--verify-result PATH] [-o PATH]` | Pre-close checks: all bugs recorded, merged, linked PR, optional verify |
| `verify --input CONTEXT [-o PATH]` | Run task `Verify:` command, full suite, and build/lint on task branch |
| `update-pr --input CONTEXT [-o PATH]` | Append bug-fix test plan to linked PR body |
| `close-bugs --input CONTEXT [--allow-partial] [-o PATH]` | Close fixed Bug sub-issues with resolution comment |
| `record-bug --input CONTEXT --bug RR-01 --commit SHA [--test-file PATH]` | Mark bug fixed in context JSON after subagent push (does **not** close GitHub issues) |
| `finish --input CONTEXT [--pr URL] [--verify-result PATH] [-o PATH]` | `merge-bugs` + `gates` (default verify) + `update-pr` + `close-bugs` + set Status **Ready to ship** |

**Agent-driven (not scripted):** parallel subagent fixes ([gh-resolve-parallel-subagents.md](gh-resolve-parallel-subagents.md)). **Scripted:** post-merge `verify` before `finish`; on verify failure the agent fixes on the task branch and re-runs `gates`.

### Context JSON

Exemplar: [gh-resolve.example.context.json](../../examples/gh-resolve.example.context.json). Key fields:

| Field | Use |
|-------|-----|
| `issue_kind` | `task` (default) or `story` — input issue type |
| `finding_kind` | `bug` (default) or `task` — GitHub sub-issue type for RR findings |
| `task_issue` | input issue (task or story): repo, number, url, title |
| `story_issue` | parent story for AC context; same as `task_issue` when `issue_kind` is `story` |
| `scope_files` / `verify_cmd` / `patterns` | from task issue; story uses bug `Involved code` union + default `pytest -q` |
| `task_branch` | `{branch, source}` — **all merges land here** |
| `linked_pr` | open PR linked to input issue (updated, not recreated) |
| `linked_pr_override` | explicit PR from `--pr` CLI |
| `gates` | result of `gates` command (`ok`, `checks[]`) |
| `merge` | merge result (`merged[]`, optional `failed` on conflict) |
| `bugs[]` | open RR sub-issues with parsed scope |
| `closed_bugs[]` | closed RR sub-issues when `resolve_status` is `complete` |
| `resolve_status` | `open` (work remaining) or `complete` (all RR bugs closed on GitHub) |
| `status_update` | result of Ready to ship project board update after `finish` (`ok`, `status`, `item_id`) |
| `hydrated_from_git` | finding IDs auto-marked `fixed` from merged remote `bug/*` branches on re-run |
| `blocker_gate` | same as gh-build |
| `local_repo_path` | resolved checkout (null → pass `--repo-path`) |

**Bug object (per sub-issue):** `finding_id`, `repo`/`number`/`url`, `scope_files`, `test_files`, `verify_cmd`, `reproduction`, `recommendation`, `proposed_branch`, `branch`, `commit`, `status` (`open` → `fixed` → `closed`).

---

## Red flags

- Creating a new PR (forbidden — update linked PR only)
- **Stopping after `record-bug`** (GitHub issues stay open until `close-bugs`)
- **Calling `close-bugs` before all bug branches are merged on task branch**
- Implementing on task branch directly during parallel phase (use bug branches)
- Skipping regression tests for testable bugs
- Skipping RED confirmation (Prove-It)
- Merging before all subagents complete and commit
- Closing parent task/story issue (leave open)
- Using `/gh-build` `open-pr` or `finish` (creates task-level PR flow)
- Editing files outside bug scope + tests
- Skipping `gates` before `finish` (unless `--no-require-verify` with justification)
- Using `--allow-partial` on `close-bugs` except in emergencies
- Handing gh-resolve commands to the user instead of running scripts yourself

---

## Verification

- [ ] Task or story issue parsed; Bug sub-issues listed
- [ ] Task/story branch checked out
- [ ] Each bug: bug branch created, Prove-It RED/GREEN, simplify, commit
- [ ] Each testable bug: regression test in suite (or documented why not)
- [ ] Bug branches merged into task branch (or skipped as already merged)
- [ ] `gates --require-verify` green on task branch
- [ ] Linked PR updated (test plan)
- [ ] Bug sub-issues closed; parent task/story issue still open
