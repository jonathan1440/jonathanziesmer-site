# gh-build — GitHub task implementation procedure

Operational contract for `/gh-build`. Load with [gh-build.md](../../gh-build.md).

Implements **one** task sub-issue created by `/gh-plan` `finish-plan`. Task issue body is canonical for scope, tests, branch, and patterns; story sub-issue is canonical for acceptance criteria.

## Contents

1. [Prerequisites](#prerequisites)
2. [State directory](#state-directory)
3. [Phase A — Prepare](#phase-a--prepare)
4. [Phase B — Implement](#phase-b--implement)
5. [Phase C — Simplify](#phase-c--simplify)
6. [Phase D — Verify loop](#phase-d--verify-loop)
7. [Phase E — Ship](#phase-e--ship)
8. [Red flags](#red-flags)
9. [Verification](#verification)
10. [Reference](#reference)

---

## Prerequisites

```bash
python3 .cursor/commands/_scripts/gh/gh-build-publish.py preflight
```

Checks `gh` ≥ 2.40, auth, and linked-branch support. Local clone of `## Repository` with `origin` pointing at the task repo (fork/name match supported).

---

## State directory

Pass `--state-dir /tmp/gh-build-<issue#>` on every scripted step. The script reads/writes predictable filenames:

| File | Written by |
|------|------------|
| `context.json` | `context`, `start`, `prepare` |
| `checkout.json` | `prepare`, `checkout` |
| `verify.json` | `verify` |
| `gates.json` | `gates`, `finalize` |
| `commit.json` | `commit-push`, `finalize` |
| `finish.json` | `finish`, `finalize` |
| `report.json` | `report`, `finalize` |

Example (issue #12):

```bash
STATE=/tmp/gh-build-12
python3 .cursor/commands/_scripts/gh/gh-build-publish.py prepare \
  --issue run-rhino/finish-photos-ui#12 --sync-story --state-dir "$STATE"
# … agent phases B–C …
python3 .cursor/commands/_scripts/gh/gh-build-publish.py verify --state-dir "$STATE"
python3 .cursor/commands/_scripts/gh/gh-build-publish.py finalize \
  --ac-attested --state-dir "$STATE"
```

Individual subcommands (`start`, `checkout`, `gates`, …) remain available for debugging. See [Reference §Scripts](#scripts).

**Agent pauses** between Phase A and Phase E for TDD, simplify, and AC gate — do not run a single script for the full pipeline.

---

## Phase A — Prepare

### Optional: read-only context

Use when you need to inspect parsed scope before any status mutation:

```bash
python3 .cursor/commands/_scripts/gh/gh-build-publish.py context \
  --issue owner/repo#12 --state-dir "$STATE"
```

Stop if required body sections are missing (`parse` errors) or `blocker_gate.passed` is false. Confirm title starts with `Task:` or issue has label `task` / type Task. Read `build_hints` for `task_kind`, `tdd_mode`, and `browser_verify_required`.

### Prepare (default)

Combines status update + branch checkout in one GitHub fetch:

```bash
python3 .cursor/commands/_scripts/gh/gh-build-publish.py prepare \
  --issue owner/repo#12 --sync-story --state-dir "$STATE"
```

**Status (first action):** sets **In-progress** via GraphQL `updateProjectV2ItemFieldValue`. On open blockers, sets **To-do** and exits 1. **Verify `status_update.ok` is true**; if false, read `status_update.warn` and retry with `--repo-path`. Use `--strict` to exit non-zero when status update fails.

**Story AC + blocker gate:** read from `context.json` — `story_issue`, `ac_ids`, `ac_scenarios`, `parent_branch`, `blocker_gate`. Story may live in a **different repo** than the task. Do not implement through open blockers unless the user explicitly overrides.

**Standalone issue (no `## Traceability`):** `story_issue` is `null`, `ac_ids`/`ac_scenarios` are empty, and `parent_branch` resolves to `{branch: <repo default branch>, source: "default_branch", exists_on_remote: true}` instead of a story branch — the task branch (`bug/<n>-slug`) is created off the default branch and the PR targets it directly. Skip `--sync-story`; there's no parent branch to sync from.

**Branch checkout:** resolves linked → body → manifest → create; git fetch/checkout; `gh issue develop`; issue body + manifest update on create. With `--sync-story`: merges `origin/{parent_branch}` when task branch has zero unique commits and is behind story branch (`checkout.story_sync.action`: `merged`, `skipped`, or `needed`).

Confirm `checkout.current_branch` equals `task_branch.branch` and `checkout.branch_issue_link.linked` is true (or `already_linked`) before editing.

Read `test_harness` from context. When `bootstrapped` is true, tier scripts (and optional `tests/test_smoke.py` for Python) were copied — allowed in scope for commit and gates. For new projects via `create_project`, run `bootstrap-harness --repo-path <path>` before first `/gh-build` if prepare has not run yet (also runs automatically at end of checkout/prepare).

Exemplar output: [gh-build.example.context.json](../../examples/gh-build.example.context.json).

### Worktree mode — running tasks in parallel

Pass `--worktree` to `prepare`/`checkout` to check the task branch out into its own linked git worktree (sibling directory, default `<repo>-worktrees/<branch-slug>`; override with `--worktree-root <dir>`) instead of in place in `--repo-path`:

```bash
python3 .cursor/commands/_scripts/gh/gh-build-publish.py prepare \
  --issue owner/repo#12 --sync-story --worktree --state-dir "$STATE"
```

`context.json` gets `local_repo_path` overwritten to the worktree path (so `verify`/`gates`/`commit-push`/`finish`/`bootstrap-harness`/`finalize` all target it automatically — no other flags needed) and a new `main_repo_path` field with the original checkout, for cleanup. Use this whenever running two or more `/gh-build` tasks side by side — without it, they'd fight over the same checked-out branch in one working directory.

After the worktree exists, set up its own Python environment before implementing (venvs are absolute-path-bound, so this can't be shared across worktrees):

```bash
cd <worktree_path>
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt -r requirements-test.txt
```

Once the task PR has merged (or the worktree is otherwise no longer needed), remove it:

```bash
python3 .cursor/commands/_scripts/gh/gh-build-publish.py cleanup-worktree \
  --input "$STATE/checkout.json"
```

Branch deletion is opt-in (`--delete-branch`) — task branches aren't auto-deleted anywhere else in this harness, so cleanup doesn't assume otherwise.

**Caveat:** commands invoked without `--state-dir`/`--input` fall back to re-discovering `local_repo_path` from `cwd`, which finds the *original* checkout, not the worktree — always pass `--state-dir` (the documented convention throughout this pipeline) when working in worktree mode.

---

## Phase B — Implement

Load [build-discipline.md](../lib/build-discipline.md). Use `build_hints.tdd_mode`: `red_green_refactor` (feature) or `prove_it` (bug).

**Scope binding:** only `## Scope` files + test files from `## Tests` (+ harness when bootstrapped; see [Reference §Harness paths](#harness-path-allowance)).

RED → GREEN → REFACTOR per increment. After each GREEN increment, run `verify` (Phase D) — not only at the end. Do not commit until scripted verify and gates pass.

When `build_hints.browser_verify_required`, load [browser-testing-with-devtools.md](browser-testing-with-devtools.md#devtools-workflow) and [#security-boundaries](browser-testing-with-devtools.md#security-boundaries).

On failure, load [debugging-and-error-recovery.md](debugging-and-error-recovery.md#stop-the-line) and [#triage-checklist](debugging-and-error-recovery.md#triage-checklist).

---

## Phase C — Simplify

After implementation verify passes and **before** commit — clarity pass on this task's changes only. Load [code-simplification.md](code-simplification.md#scope) and [#simplification-process](code-simplification.md#simplification-process).

Re-run `verify` (Phase D) after simplifications.

---

## Phase D — Verify loop

```bash
python3 .cursor/commands/_scripts/gh/gh-build-publish.py verify --state-dir "$STATE"
```

Runs in order, stopping analysis at the first failure (when tier scripts exist under `scripts/`):

1. `scripts/test-tier1-lint.sh` — lint/type checks (stack-detected)
2. `scripts/test-tier2-unit.sh` — unit tests (`exit 2` → `harness_missing: true`)
3. `scripts/test-tier3-security.sh` — secret scan, dependency audit, IAM/policy (`exit 2` → `skipped: true`, not a failure)
4. `scripts/test-tier4-integration.sh` — single-service integration (CDK synth / LocalStack; `exit 2` → `skipped: true`)
5. Task `verify_cmd` from issue body (required; task-narrow only)

Tiers 5–6 are exercised at story/spec-level `/gh-review`, not per task (outline §3 gating table).

**Fallback** when no tier scripts exist: legacy `pytest -q` / `npm test` suite + `ruff check .` / `npm run build`.

Both `verify` and `gates` must return exit 0 before commit. Exit 1 example: [gh-build.example.verify-failure.json](../../examples/gh-build.example.verify-failure.json).

<a id="verify-loop-rules"></a>

### Verify loop rules

1. `tiers.tier1.exit_code != 0` → fix lint/type errors → re-run verify
2. `tiers.tier2.harness_missing` or `exit_code == 2` → run `bootstrap-harness --repo-path <repo>` or add test scaffold → re-run verify
3. `tiers.tier2.exit_code == 1` → fix failing unit tests → re-run verify
4. `tiers.tier3.exit_code` not in (0, 2) → fix the security finding (secret, CVE, policy) → re-run verify
5. `tiers.tier4.exit_code` not in (0, 2) → fix the integration failure (synth error, service startup) → re-run verify
6. `verify_cmd.exit_code != 0` → fix task-narrow test failure → re-run verify
7. After 3 iterations on the same failure class → comment summary on the task issue, @-mention the story owner, and stop (blocker)

Read `output_tail` on each failed step for fix guidance. Do not hand-roll `ruff`/`pytest` when tier scripts exist — use the tier output.

---

## Phase E — Ship

### AC gate (agent)

Confirm every cited `AC-*` scenario from the parent story is satisfied **before** commit or finalize.

### Finalize (default)

After AC gate and verify exit 0:

```bash
python3 .cursor/commands/_scripts/gh/gh-build-publish.py finalize \
  --ac-attested --state-dir "$STATE"
```

Runs `gates --require-verify` → `commit-push` → `finish --strict` → `report`. `--ac-attested` is required (honor-system attestation that AC gate passed). Default `--strict` on commit/finish: fails when gates, commit, PR, or status update fail.

Creates or finds PR task branch → parent story branch. PR body includes `Closes owner/repo#N`. Sets **Review / QA** on project board. Check `pr.url`, `pr.task_issue_link`, `pr.ok` / `pr.skipped`, and `status_update.ok`. Leave task issue **open**.

Exemplar report: [gh-build.example.report.json](../../examples/gh-build.example.report.json).

### Individual steps (debug)

```bash
python3 .cursor/commands/_scripts/gh/gh-build-publish.py gates \
  --state-dir "$STATE" --require-verify
python3 .cursor/commands/_scripts/gh/gh-build-publish.py commit-push \
  --state-dir "$STATE"
python3 .cursor/commands/_scripts/gh/gh-build-publish.py finish \
  --strict --state-dir "$STATE"
python3 .cursor/commands/_scripts/gh/gh-build-publish.py report \
  --state-dir "$STATE"
```

`gates` checks: `blocker_gate`, on task branch, not main/story/spec branch, scope discipline. `--allow-out-of-scope` escape hatch for commit-push/gates only (justify in PR).

`commit-push` auto-includes new/modified `__init__.py` files for touched packages. Fails when nothing staged after add.

---

## Red flags

- Skipping gh-build-publish.py for parse, status, branch, verify, gates, commit, PR
- Hand-rolling `gh project`, `git commit`, or `gh pr create` when script is available
- Ignoring `verify.ok` or `gates.ok` before commit
- Running `finalize` without `--ac-attested` or before AC gate
- Implementing on story branch, `main`, or `spec/<slug>`
- Editing files outside scope (gates should catch this)
- Bypassing tier scripts with hand-rolled lint/test when `scripts/test-tier*.sh` exist
- Skipping `finish --strict` Review / QA status update
- Ignoring `status_update.ok` on prepare/start/finish

---

## Verification

Read `report.json` in `--state-dir` (or individual step JSON):

- [ ] `status_update.ok` true on prepare (or warn documented)
- [ ] On correct task branch (`gates.checks.task_branch`)
- [ ] `verify.ok` and `gates.ok` true
- [ ] Commit SHA in report
- [ ] PR URL or skipped with reason
- [ ] `status_update.ok` true on finish (Review / QA)
- [ ] Agent attested AC, TDD, simplify

---

## Reference

### Scripts

Path: `.cursor/commands/_scripts/gh/gh-build-publish.py`

| Command | Purpose |
|---------|---------|
| `preflight` | gh version + auth + linked-branch support |
| `context --issue REF` | Parse task, story AC, branches, blockers, `build_hints` → JSON (read-only) |
| `prepare --issue REF [--sync-story]` | `context` + Status **In-progress** + checkout + harness bootstrap |
| `start --issue REF` | `context` + set Status **In-progress** (To-do when blocked) |
| `checkout --issue REF [--sync-story] [--worktree]` | Resolve/create task branch, git checkout (or linked worktree), link branch, bootstrap test harness |
| `cleanup-worktree --input CHECKOUT.json [--delete-branch]` | Remove a worktree created by `prepare`/`checkout --worktree` |
| `verify --input CONTEXT.json` | Run tier 1–4 scripts, task verify, legacy suite/build fallback |
| `bootstrap-harness --repo-path PATH` | Copy tier scripts + optional pytest smoke scaffold (new projects) |
| `gates --input CONTEXT.json [--require-verify]` | Pre-commit mechanical checks |
| `commit-push --input CONTEXT.json` | Gates + stage scope/tests + commit + push |
| `finalize --input CONTEXT.json --ac-attested` | gates + commit-push + finish + report |
| `open-pr --input CONTEXT.json` | Link branch + create/find PR task → parent branch |
| `finish --input CONTEXT.json [--strict]` | `open-pr` + set Status **Review / QA** |
| `set-status --issue REF --status in-progress\|review-qa\|todo` | Project Status only |
| `report --input CONTEXT.json [...]` | Assemble present-output summary JSON |

**Agent-driven (not scripted):** TDD implementation, simplify pass, browser MCP verify, AC confirmation.

### Context JSON

Exemplar: [gh-build.example.context.json](../../examples/gh-build.example.context.json). Key fields:

| Field | Use |
|-------|-----|
| `task_issue` | repo, number, url, title |
| `story_issue` | parent story repo, number, id — `null` for a standalone issue (no `## Traceability`) |
| `ac_ids` / `ac_scenarios` | cited acceptance criteria |
| `scope_files` / `test_files` / `verify_cmd` | binding edit + test list |
| `blocker_gate` | `{passed, open_blockers}` |
| `task_branch` | `{branch, source}` |
| `parent_branch` | `{branch, exists_on_remote, source}` — PR base |
| `local_repo_path` | resolved checkout (null → pass `--repo-path`) |
| `manifest_path` | gh-spec.manifest.json when found |
| `project` | board owner/number/id for status updates |
| `build_hints` | `{task_kind, tdd_mode, browser_verify_required}` |
| `status_update` | result from start/prepare |
| `checkout` / `test_harness` | from prepare/checkout |

### Strict mode

| Command | Default strict | Effect |
|---------|----------------|--------|
| `start` / `prepare` | off | `--strict` → exit 1 when status update fails |
| `finish` / `finalize` | on | exit 1 when PR fails (non-skipped) or status update fails |
| `commit-push` | on | runs gates with `--require-verify` before commit |
| `gates` | on | exit 1 when any check fails |

Use `--no-strict` to warn-only.

<a id="harness-path-allowance"></a>

### Harness path allowance

Harness paths always allowed when on disk (scope discipline + gates):

- `scripts/test-tier*.sh` (tiers 1–7 plus `test-tier*-local.sh` overrides)
- `scripts/test-tiers.sh`, `scripts/test-tiers-12.sh`
- bootstrapped `tests/test_smoke.py`
