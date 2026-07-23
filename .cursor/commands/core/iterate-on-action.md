---
name: iterate-on-action
description: Commit and push relevant changes (via commit-push), then drive GitHub Actions to green using gh—avoid duplicate runs, watch logs, fix, repeat.
---

# Loop on CI (commit, push, watch, iterate)

## When to use

- You need **branch CI or a specific workflow** to pass and are willing to **commit fixes** until it is green.
- The user asks to **test a workflow**, **iterate on Actions**, **fix CI**, or **watch pipeline logs** until success.

Do **not** use when the user only wants a one-off log peek with **no** commit/push loop, or when they forbid pushing.

## Prerequisites

- `git` and `gh` available, `gh auth status` succeeds for the target repo.
- Know **which** workflow matters when not obvious: path under `.github/workflows/` (e.g. `deploy.yml`) or the workflow name. If unclear, ask once or infer from recent edits.

## High-level loop

1. **Land changes:** if there are relevant uncommitted changes, run the **`commit-push`** skill (uses `commit`, then push). If the tree is already clean, skip to step 2.
2. **Find or start a run without duplicating work:** list runs for this branch (and workflow if specified). If an applicable run is already **in progress or queued**, **watch that run**—do **not** run `gh workflow run` again unless the user explicitly wants a second run.
3. **Wait and read results:** `gh run watch` on the chosen run; on failure, pull failed logs and fix the **first actionable** error.
4. **Repeat:** `commit-push` again if you made fixes, then go back to step 2 until the required checks pass or the user stops you.

---

## 1. Working tree and push

1. `git status`. If there is nothing to commit and nothing unpushed, continue.
2. If there are changes to include:
   - Invoke the **`commit-push`** skill so changes become a conventional commit and are pushed to the tracked remote.
   - If commit hooks fail, fix the underlying issue; do not use `--no-verify` unless the user explicitly allows it.
3. Record **branch name** and **HEAD SHA** (for example `git rev-parse HEAD`) for matching runs after the push.

---

## 2. Read before you trigger (avoid duplicate runs)

`gh workflow run` **always** creates a **new** run. Before any dispatch:

1. List recent runs for the current branch (add `-R owner/repo` if not in the repo directory):

   ```bash
   git branch --show-current
   gh run list --branch "$(git branch --show-current)" -L 15 \
     --json databaseId,status,conclusion,name,headSha,url,workflowName
   ```

2. If the user cares about **one workflow file**, narrow with `-w`:

   ```bash
   gh run list -w .github/workflows/<workflow-file>.yml \
     --branch "$(git branch --show-current)" -L 10 \
     --json databaseId,status,conclusion,headSha,url
   ```

3. Treat these statuses as **already running—do not dispatch again** unless the user asked for a duplicate run: `queued`, `in_progress`, `requested`, `waiting`, `pending`.

4. **If** a run for this branch (and workflow, if specified) is already active: set `RUN_ID` to its `databaseId` and go to **section 3**.

5. **If** no active run exists:
   - **Push-triggered workflows:** the push in section 1 should enqueue a run. Wait a few seconds and re-list; pick the run whose `headSha` matches `HEAD` when possible.
   - **`workflow_dispatch` only:** only then run `gh workflow run -w .github/workflows/<file>.yml` (with `-f` inputs if required), then list runs again and pick the new run’s id.

6. If you cannot find a run after a push, re-list with `--commit <SHA>`:

   ```bash
   gh run list --commit "$(git rev-parse HEAD)" -L 10 --json databaseId,status,url,name
   ```

---

## 3. Watch and inspect

Use the run id from section 2 (`RUN_ID`).

```bash
# Block until finished; non-zero exit if the run fails
gh run watch "$RUN_ID" --exit-status
```

If you need logs without blocking first:

```bash
gh run view "$RUN_ID" --log-failed
```

For full logs when needed:

```bash
gh run view "$RUN_ID" --log
```

---

## 4. On failure: fix, commit-push, repeat

1. Summarize the **first** root cause from logs (not every warning at once).
2. Apply the **smallest** fix that addresses that cause.
3. Run **`commit-push`** again.
4. Go to **section 2**. Prefer watching the **new** run tied to the new commit SHA.

Stop after a reasonable number of iterations or if the failure is outside the repo (permissions, secrets, GitHub settings). Say so clearly and list what a human must change.

---

## Guardrails

- **One failure theme per commit** when possible; avoid mixing refactors with CI fixes.
- **No** `--no-verify` to green the loop unless the user explicitly approves.
- **No** force-push unless the user explicitly requests it and understands the risk.
- If a failure looks **flaky**, retry the **same** fix path once and record evidence (job name, log snippet).

## Output

Each cycle, report:

- Whether you committed/pushed and the short commit subject.
- **Run id** and URL you watched.
- Pass/fail and, if fail, the error you fixed next.

When done: required checks green (or which check still fails and why).
