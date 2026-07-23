# GitHub issue labels vs native fields (cursor command scripts)

Inventory of where `.cursor/commands/_scripts/` touches GitHub issue **labels**, and which native issue fields (issue type, project status, body metadata, etc.) serve the same role.

Only `gh-spec-publish.py` runs `gh issue create --label` or `gh issue edit --remove-label`. Other publish scripts set **issue types** instead of labels.

## Script operations on GitHub issues

| Location | Operation | Label(s) | Corresponding GitHub field | Native field also set? | Notes |
|----------|-----------|----------|----------------------------|------------------------|-------|
| `gh-spec-publish.py` → `create_issue()` | Add on create (`gh issue create --label`) | Any passed in `labels` arg | **Issue type** (hierarchy: Spec / User Story / Task) | **Yes** — `--type` on create when CLI supports it; else `ensure_issue_type()` after create | **Dead path today:** `labels_for_layer()` always returns `[]`; callers always pass `issue_type`, so create uses `--type`, not `--label` |
| `gh-spec-publish.py` → `strip_legacy_hierarchy_labels()` | Remove (`gh issue edit --remove-label`) | `spec` | **Issue type** → Spec | **Yes** — `ensure_issue_type()` / `gh issue edit --type` / GraphQL `updateIssueIssueType` | Called from `ensure_hierarchy_issue_classification()` |
| `gh-spec-publish.py` → `strip_legacy_hierarchy_labels()` | Remove | `user-story` | **Issue type** → User Story | **Yes** | Same |
| `gh-spec-publish.py` → `strip_legacy_hierarchy_labels()` | Remove | `task` | **Issue type** → Task | **Yes** | Same |
| `gh-spec-publish.py` → `ensure_hierarchy_issue_classification()` | Set type (not a label) | — | **Issue type** → Spec | **Yes** | Parent spec issue: `cmd_publish`, `fix-hierarchy-types` |
| `gh-spec-publish.py` → `ensure_hierarchy_issue_classification()` | Set type (not a label) | — | **Issue type** → User Story | **Yes** | Story issues: `publish_stories`, `fix-hierarchy-types` |
| `gh-spec-publish.py` → `ensure_hierarchy_issue_classification()` | Set type (not a label) | — | **Issue type** → Task | **Yes** | Task issues: `publish-plan` / `finish-plan`, `fix-hierarchy-types` |
| `gh-review-publish.py` → `sync_one_finding()` → `create_issue()` | Create (no labels) | _(none — `labels=[]`)_ | **Issue type** → Bug | **Yes** — `issue_type="Bug"` for CONFIRM findings | Procedures forbid legacy `bug` label |
| `gh-review-publish.py` → `sync_one_finding()` → `create_issue()` | Create (no labels) | _(none — `labels=[]`)_ | **Issue type** → Task | **Yes** — `issue_type="Task"` for TRACK findings | Follow-up work items, not hierarchy tasks |
| `gh-build-publish.py` | — | _(none)_ | **Project status** (Todo / In progress) | **Yes** — `set_project_status()` | No label or issue-type changes |
| `gh-promote.py` | — | _(none)_ | **Project status** (Review / QA) | **Yes** — on parent promotion | No label or issue-type changes |
| `gh-resolve-publish.py` | — | _(none)_ | — | — | Reads `issueType`; edits bodies; no label ops |
| Handoff scripts (`handoff/*.py`) | — | _(none)_ | — | — | No GitHub issue label ops |

### `ensure_hierarchy_issue_classification()` call sites

| Command / function | Issue layer | Label removed (if present) | Issue type set |
|--------------------|-------------|----------------------------|----------------|
| `cmd_publish` | Parent (Spec) | `spec` | Spec |
| `publish_stories` | Story (US-*) | `user-story` | User Story |
| `publish-plan` / `finish-plan` | Work (task) | `task` | Task |
| `fix-hierarchy-types` | Parent, all stories, all work issues | all three | per manifest `issue_types` |

## Procedure vocabulary (not applied as GitHub labels by scripts)

These “labels” appear in cursor command procedures or triage output. Scripts do **not** call `gh issue edit --add-label` for them.

| Location | Name | Applied to GitHub issue? | Corresponding field (if any) | Set by scripts? |
|----------|------|--------------------------|------------------------------|-----------------|
| `research-issues-procedure.md` | `LEGITIMATE_NOW`, `LEGITIMATE_DEFER`, `HYPOTHETICAL`, `INVALID` | **No** — triage markdown only | — | **No** |
| `triage-surface-area-groups.md` | `SA1` … `SA6` | **No** — Owner column in triage doc | `owner_sa` in review payload → issue **body** | **No** (body only via `gh-review-publish.py`) |
| `gh-review` procedures | `CONFIRM`, `TRACK`, `DISMISS` | **No** as labels | CONFIRM/TRACK → **issue type** Bug/Task on filed sub-issues; disposition in triage doc + issue body | Partial — types only for CONFIRM/TRACK sub-issues |
| Spec / plan procedures | Priority labels (P1, P2, …) | **No** — explicitly banned in story format | — | **No** |
| `gh-spec-publish.py` → `normalize_issue_hierarchy_payload()` | `spec`, `user-story`, `task` in publish JSON `labels` key | **No** — stripped from payload | **Issue type** from `types` key | **Yes** — types, not labels |
| `gh-plan-research-procedure.md`, `planning-shared.md` | _(read only)_ | Scripts **read** `labels` via `gh issue view --json labels` | — | **No** writes |

## Doc / code mismatch

`gh-spec-github-procedure.md` (§Flat fallback) states that when sub-issues are unavailable, publish uses **legacy labels**. Current `gh-spec-publish.py` does not add hierarchy labels on create; it sets **issue types** and uses a `Parent: #N` footer in the story body for flat hierarchy.
