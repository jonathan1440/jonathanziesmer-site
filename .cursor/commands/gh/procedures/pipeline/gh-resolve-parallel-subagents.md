---
name: gh-resolve-parallel-subagents
description: Parallel subagent contract for /gh-resolve-issues — one Bug per agent, branch isolation, parent integration.
---

# gh-resolve — parallel subagents

Load with [gh-resolve-issues-github-procedure.md](gh-resolve-issues-github-procedure.md) Phase 3 and [dispatching-parallel-agents.md](../lib/dispatching-parallel-agents.md).

## Concurrency model

1. **Parent (sequential):** run `create-bug-branch` for **every** bug in `bugs[]` before dispatch — pass `--worktree` so each bug gets its own linked git worktree instead of sharing one checkout (required for true concurrency; see below).
2. **Subagents (parallel):** one Bug each on `bug/<finding-id>-<slug>`, working in its own `worktree_path`.
3. **Parent (sequential):** `record-bug` after each subagent returns; then merge, gates, finish.

Subagents must **not** write the shared context JSON during parallel work — commit and push on their bug branch, then return metadata to the parent.

**Why `--worktree` matters here:** without it, `create-bug-branch` and every per-bug script call (`commit-push`, `verify`, ...) default to the single shared `local_repo_path` — fine for the parent's sequential branch-creation loop, but genuinely parallel subagents would then race on `git checkout` in one directory. `create-bug-branch --worktree` gives each bug its own directory (sharing one `.git`) and records it as `worktree_path` on that bug's entry in context.json; passing `--repo-path <worktree_path>` on every subsequent per-bug call (which already wins over the shared `local_repo_path`) is what actually makes the subagents safe to run concurrently.

## Model

Every bug-fix Task must use **`model: composer-2.5`** (same economics as `/gh-build`). Do not inherit a frontier parent model for leaf fixes.

## Subagent prompt must include

- Context file path and `finding_id`
- This bug's own working directory (`worktree_path` from its context.json entry) — pass as `--repo-path` on every scripted call; **do not** use the shared `local_repo_path`
- Bug URL, `scope_files`, `recommendation`, `reproduction`
- Task `verify_cmd` and `patterns`
- Load [bug-fix-discipline.md](../lib/bug-fix-discipline.md)
- **Do not:** merge, open PR, touch other bugs' branches, write context JSON

## Per-bug workflow

Follow [bug-fix-discipline.md](../lib/bug-fix-discipline.md). Optional scripted commit:

```bash
python3 .cursor/commands/_scripts/gh/gh-resolve-publish.py commit-push \
  --input "$STATE/context.json" --bug RR-01 --repo-path "$WORKTREE_PATH" -o "$STATE/context.json"
```

Parent may run `commit-push` when a subagent did not push. Omit `--repo-path` (falls back to the shared `local_repo_path`) only when `--worktree` was not used for `create-bug-branch`.

## Subagent return payload

| Field | Required |
|-------|----------|
| `finding_id` | Yes |
| `commit` | Yes — SHA on bug branch |
| `branch` | Yes |
| `files_changed` | Yes |
| `test_files` | When added |
| `verify_output` | Yes |

## Parent after all subagents return

```bash
python3 .cursor/commands/_scripts/gh/gh-resolve-publish.py record-bug \
  --input "$STATE/context.json" --bug RR-01 --commit <SHA> \
  --test-file path/to/regression.test.ts -o "$STATE/context.json"
```

**`record-bug` updates local context only — GitHub Bug issues stay open until `close-bugs`.**

Then:

- Confirm every bug has `status: fixed` via `record-bug`
- Resolve merge conflicts when merging bug branches (prefer bug-branch intent)
- Proceed to Phase 4 merge + gates ([procedure §Phase 4](gh-resolve-issues-github-procedure.md#phase-4--merge-gates--publish))

## Branch + directory isolation

- Work only on `bug/<finding-id>-<slug>`, branched from task/story branch
- With `--worktree`: also work only inside that bug's own `worktree_path` — never the shared `local_repo_path` or another bug's worktree
- Scope: bug `scope_files` + new/updated test files; task `## Scope` is the outer boundary
- After a bug branch merges (Phase 4), its worktree is no longer needed: `python3 .cursor/commands/_scripts/gh/gh-build-publish.py cleanup-worktree --repo-path <main_repo_path> --worktree-path <worktree_path>`
