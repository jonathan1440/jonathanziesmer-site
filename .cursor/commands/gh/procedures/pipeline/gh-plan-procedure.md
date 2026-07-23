# gh-plan — Procedure

Operational contract for `/gh-plan`. Load with [gh-plan.md](../../gh-plan.md), [planning-shared.md](planning-shared.md), and [gh-plan-research-procedure.md](gh-plan-research-procedure.md).

**Publish task sub-issues immediately** after research — no `plan.md`, no human approval gate. Implementation detail lives in task bodies; story-level notes go on the input issue.

## Contents

1. [Prerequisites](#prerequisites)
2. [Inputs](#inputs)
3. [Context resolution](#context-resolution)
4. [Target repos](#target-repos)
5. [Local checkout mapping](#local-checkout-mapping)
6. [Branch sync](#branch-sync)
7. [Task decomposition](#task-decomposition)
8. [Task issue bodies](#task-issue-bodies)
9. [Story issue — Implementation notes](#story-issue--implementation-notes)
10. [Publish payload](#publish-payload)
11. [Blocker rules](#blocker-rules)
12. [Commands](#commands)
13. [Manifest `work_issues`](#manifest-work_issues)
14. [Project Estimate field](#project-estimate-field)
15. [Red flags](#red-flags)
16. [Verification](#verification)

---

## Prerequisites

```bash
gh --version          # ≥ 2.40
gh auth status        # needs repo + project scopes for board attachment
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py preflight
```

`preflight` checks GraphQL `addSubIssue` and `addBlockedBy`.

---

## Inputs

| Input | Required | Example |
|-------|----------|---------|
| `story_issue` | Yes | `run-rhino/finish-photos#20` or issue URL |
| `manifest_path` | No | `docs/specs/video-preview-flip/gh-spec.manifest.json` |
| `project` | No | From manifest — blocker status filter for agent research |
| `workspace_roots` | No | `[cwd, parent(cwd)]` default |

---

## Context resolution

See [planning-shared.md §Context resolution](planning-shared.md#context-resolution).

---

## Target repos

See [planning-shared.md §Target repos](planning-shared.md#target-repos).

---

## Local checkout mapping

See [planning-shared.md §Local checkout mapping](planning-shared.md#local-checkout-mapping).

---

## Branch sync

Run on the **home repo** checkout **before** research subagents. Full semantics: [branch-sync-procedure.md](branch-sync-procedure.md).

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py sync-plan-branches \
  --manifest-path docs/specs/<slug>/gh-spec.manifest.json \
  --story-id US-01 \
  --repo-path /path/to/home-repo \
  --mode plan \
  --other-repo run-rhino/finish-photos-ui:/path/to/ui
```

**Agent interprets JSON:**

| `blocked_reason` | Action |
|------------------|--------|
| *(none)* / `status: ok` | Continue to subagents |
| `branch_started` + `require_user_confirm: true` | Stop; present sync JSON `user_message`; proceed only if user explicitly confirms |
| `rebase_conflict` | Stop; present sync JSON `user_message`; do not research on dirty tree |

Repeat `--other-repo` for each non-home listed checkout (fetch + checkout story/spec branch only — no auto-rebase there).

---

## Task decomposition

Plan-specific rules (discovery rules: [gh-plan-research-procedure.md](gh-plan-research-procedure.md)):

| Rule | Detail |
|------|--------|
| One repo per task | `task.repo` is where the issue is created |
| Sub-issue parent | Always the **input story issue** (may be different repo than task) |
| Task ID | `US-01-TASK-01` when manifest has `US-01`; else `<story#>-TASK-01` |
| Task branch | `task/US-01-<task-title-slug>` — linked via `gh issue develop` on `finish-plan` |
| Duration | `duration_estimate` per task (e.g. `2h`, `0.5d`) — issue body **and** Project **Estimate** when configured |
| Decisions | `decisions[]` — planner-locked choices; build must not reopen them |
| Tests | `tests.files[]` + task-narrow `tests.verify` only |

**Planner collapses ambiguity (cost dial):** `/gh-build` runs on Composer. Worker tokens explode when Scope leaves design open. For every tradeoff (library, API shape, error path, where state lives), **choose one** in `decisions[]` and reflect it in `files[].change`. Put rejected options in research **Out of scope**, not in the task body. Ambiguous wording (`either` / `or` / `consider` / `maybe` / `TBD`) in `description` or `files` is a red flag — fix before `finish-plan`.

**Tests section rules:**

- `Verify:` must be **task-narrow** (e.g. `pytest tests/handlers/test_upload.py::test_returns_200 -q`, `npm test -- SubmitForm`) — not full-suite commands
- Tier 1–2 run via `scripts/test-tier*.sh` when bootstrapped on checkout
- **Brownfield (non-Python):** prepend `TASK-00: Add tier 1–2 test harness` when repo lacks tier scripts

---

## Task issue bodies

Do **not** author task markdown manually. Build publish JSON per [gh-plan.example.publish.json](../../examples/gh-plan.example.publish.json); `finish-plan` renders via `render_work_body_v2` in `gh-spec-publish.py`.

| Payload field | Issue output |
|---------------|--------------|
| `tasks[].title`, `description` | Title `Task: …`; **Task** section |
| `tasks[].repo` | **Repository** |
| `tasks[].acceptance`, `duration_estimate` | **Traceability** |
| `tasks[].decisions`, `files`, `tests`, `patterns` | **Decisions**, **Scope**, **Tests**, **Patterns** |
| `blockers` | **Dependencies** (final pass after all tasks exist) |
| `story_notes` | Replaces `## Implementation notes` on the story issue |

---

## Story issue — Implementation notes

Append/replace `## Implementation notes` on the **input story issue** (idempotent replace by heading). Shape: [_templates/planning/story-implementation-notes.example.md](../../../_templates/planning/story-implementation-notes.example.md).

Generic cross-task guidance only — per-file scope stays in task issues.

---

## Publish payload

**Shape:** [gh-plan.example.publish.json](../../examples/gh-plan.example.publish.json).

Required: `story_issue` (`repo`, `number`, `id`), `types.work` (`"Task"`), `tasks[]`. Optional: `story_notes`, `blockers[]`, `exclude_statuses`.

Do **not** include `labels` in plan payloads. Per-task: `id`, `repo`, `title`, `description`, `acceptance`, `duration_estimate`, `decisions[]` (locked choices), `files[]`, `tests` (`files`, `verify`), `patterns[]`.

---

## Blocker rules

**Sources (both):**

1. **Intra-plan:** task ordering (API contract before UI proxy, etc.)
2. **External:** open project issues where Status ∉ exclude list (default: `Shipped`, `Ready to ship`), in repos touched by this plan

**Direct only:** if A blocks B and B blocks C, attach **B → C** only, not A → C.

**Final pass:** script runs `addBlockedBy` **after** all task issues exist.

**Cap:** max 3 external blockers per task; record `reason` in payload.

### Blocker discovery (agent, before payload)

```bash
gh project item-list <project_number> --owner <owner> --format json
gh project field-list <project_number> --owner <owner> --format json
```

Filter items where `status` not in `exclude_statuses` (case-insensitive). Match by: spec parent link, shared labels, title/AC overlap, explicit `depends on` / `blocks` in bodies.

---

## Commands

**Agent runs via Shell — not the user.**

1. **Research → payload** — subagents per [gh-plan-research-procedure.md](gh-plan-research-procedure.md); parent merges blockers
2. **`finish-plan`** (required):

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py finish-plan \
  --input /tmp/gh-plan-payload.json \
  --manifest-path docs/specs/<slug>/gh-spec.manifest.json
```

Runs `publish-plan` + `verify-plan`. **Do not** stop after research or ask the user to run this.

`finish-plan` also: links `task/US-*` branches via `gh issue develop`; sets Project **Estimate** from `duration_estimate`; idempotent on `tasks[].id` — [planning-shared.md §finish-plan idempotency](planning-shared.md#finish-plan-idempotency).

3. **Debug only:** `publish-plan` / `verify-plan` separately when isolating failures.

---

## Manifest `work_issues`

Schema **v1.1** — see [gh-spec.example.manifest.json](../../examples/gh-spec.example.manifest.json) `work_issues` (includes `branch`, `story_issue`, `blockers`). Set `schema_version` to `v1.1` when using these fields.

---

## Project Estimate field

When `duration_estimate` is set and a GitHub Project is configured, `finish-plan` sets org **Estimate** from the same value (warn-only on failure).

---

## Red flags

See also [gh-plan.md](../../gh-plan.md) **Critical rules**.

- Authoring task issue markdown manually — JSON payload only
- Writing `tasks/plan.md` for gh-plan flow
- Waiting for human approval before creating issues
- Attaching work issues to spec parent instead of story issue
- Transitive blockers (A→C when only B→C is direct)
- Researching repos not on the story issue list
- Tasks without tests or verify command; multi-repo single task
- Parent researches code when listed repos have local checkouts
- Rebasing when sync script reports started branches (without user confirm)
- Skipping branch sync when manifest has `spec_branch` and story `branch`
- Ambiguous task bodies — `either`/`or`/`consider`/`maybe`/`TBD` in `description` or `files[].change`; missing `decisions[]` when a tradeoff existed
- Open-ended Scope that forces `/gh-build` to re-decide design

---

## Verification

- [ ] Branch sync completed (or skipped with documented reason) on home repo before subagents
- [ ] Target repos from story issue or manifest only (count matches list)
- [ ] One research subagent per **listed** repo with checkout (or NO_CHECKOUT in `story_notes`)
- [ ] Every task has `files`, `tests`, `duration_estimate`, `acceptance` AC IDs
- [ ] Every task has `decisions[]` when any design tradeoff existed (or AC already fully constrains)
- [ ] No ambiguous Scope wording (`either`/`or`/`consider`/`maybe`/`TBD`) in task `description` or `files`
- [ ] Task IDs assigned; one repo per task; direct blockers only
- [ ] Payload matches [gh-plan.example.publish.json](../../examples/gh-plan.example.publish.json)
- [ ] Task issues have linked `task/US-*` branches; **Estimate** set when project configured
- [ ] `preflight` reports sub_issues + blocked_by support
- [ ] Tasks as sub-issues of story issue (possibly cross-repo)
- [ ] Story issue has `## Implementation notes`; blockers visible in GitHub UI
- [ ] Manifest `work_issues` updated (when manifest path provided)
