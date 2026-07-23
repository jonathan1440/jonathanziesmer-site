# gh-review — GitHub publish procedure

Operational contract for `/gh-review`. Load with [gh-review.md](../../gh-review.md) and [gh-review-procedure.md](gh-review-procedure.md).

Triage semantics: [gh-review-triage-rules.md](gh-review-triage-rules.md). RR-IDs: [gh-review-rr-ids.md](gh-review-rr-ids.md).

---

## Prerequisites

```bash
gh --version          # ≥ 2.40 recommended
gh auth status
python3 .cursor/commands/_scripts/gh/gh-review-publish.py preflight
```

`preflight` checks GraphQL `addSubIssue` (required for hierarchy). If unavailable, script still creates issues but cannot link sub-issues — **stop** and document flat fallback per [gh-spec-github-procedure.md](gh-spec-github-procedure.md).

Org must define issue types **Bug** and **Task**.

---

## Scripts

| Command | Purpose |
|---------|---------|
| `preflight` | Sub-issue support check |
| `context --issue REF -o PATH` | Issue graph, PRs, branches, scope hints, `story_issue`, `rr_id_registry` → JSON |
| `init-payload --context PATH [-o PATH]` | Scaffold payload from context |
| `init-triage-doc --context PATH [-o PATH] [--force]` | Scaffold triage markdown from templates |
| `resolve-target --context PATH [-o PATH]` | PR / branch review target from context |
| `validate-payload --input PATH [--strict]` | Payload shape + triage rule checks |
| `check-consistency --input PATH [--triage PATH]` | Payload RR-IDs ↔ triage markdown |
| `sync-bugs --input PAYLOAD [-o SUMMARY] [--dry-run]` | Create / update / close Bug + Task sub-issues |
| `comment --input PAYLOAD --sync-summary SUMMARY [--dry-run]` | Post summary on reviewed issue |
| `publish --input PAYLOAD [-o SUMMARY] [--dry-run]` | `validate-payload` → `sync-bugs` → `comment` |

Path: `.cursor/commands/_scripts/gh/gh-review-publish.py`

Templates: `.cursor/commands/_templates/gh-review/`. JSON Schema: [gh-review.payload.schema.json](../../../_templates/gh-review/gh-review.payload.schema.json).

Full sequence: [gh-review-procedure.md](gh-review-procedure.md) Phases 0 and 4.

---

## Payload schema (`sync-bugs` / `comment`)

| Field | Required | Notes |
|-------|----------|-------|
| `review_issue` | Yes | `{repo, number, url, title}` — **parent for Bug and Task** sub-issue links |
| `story_issue` | No | User story for traceability in finding bodies — **not** the Task sub-issue parent |
| `review_date` | Yes | `YYYY-MM-DD` |
| `triage_path` | Yes | Repo-relative path to triage markdown |
| `aggregate_verdict` | Yes | `FAIL` \| `PASS_WITH_NOTES` \| `PASS` |
| `findings[]` | Yes | All RR-IDs from review + triage |
| `branches[]` | Yes | From `context` output; copied into each synced issue |
| `pr` | No | Best linked PR when present |
| `issue_type` | No | Default `Bug` (CONFIRM findings) |
| `followup_issue_type` | No | Default `Task` (TRACK findings) |
| `parent_issues` | No | Epic/spec ancestors; traceability only |
| `scope_hints` | No | Includes optional `story_issue_number` for finding-body context |
| `rr_id_registry` | No | Copy from `context` when assigning RR-IDs |
| `project` | No | `{title}` for project attachment on create |

Every payload **must** include `"issue_type": "Bug"` and `"followup_issue_type": "Task"`. See [gh-review.example.payload.json](../../examples/gh-review.example.payload.json).

### Finding object

| Field | Required | Notes |
|-------|----------|-------|
| `id` | Yes | `RR-01` … |
| `disposition` | Yes | `CONFIRM` \| `TRACK` \| `DISMISS` |
| `severity` | Yes | CRITICAL / HIGH / MEDIUM / LOW |
| `summary` | Yes | One line; becomes issue title suffix |
| `repo` | CONFIRM / TRACK | `owner/name` where work lives; defaults to `review_issue.repo` |
| `rationale` | Yes | 2–4 sentences |
| `evidence` | Yes | String list (`path:line — fact`) |
| `paths` | CONFIRM / TRACK | `[{path, role}]` involved code table |
| `reproduction` | No | Steps; omit when N/A |
| `recommendation` | Yes | Fix direction, not implementation |
| `owner_sa` | No | SA label from triage grouping |
| `dismiss_reason` | DISMISS only | See [gh-review-triage-rules.md](gh-review-triage-rules.md) — **never** `hygiene` or `test-hygiene` |
| `track_reason` | TRACK only | See [gh-review-triage-rules.md](gh-review-triage-rules.md) |
| `branches` | No | Override per-finding; defaults to payload `branches` |

Only `CONFIRM` and `TRACK` rows are synced to GitHub. `DISMISS` rows inform close comments for stale issues.

---

## Issue shapes

**Title:** `[RR-NN] <summary>` (max ~120 chars on summary)

| Disposition | Type | Sub-issue parent |
|-------------|------|------------------|
| CONFIRM | Bug | `review_issue` |
| TRACK | Task | `review_issue` — the input issue; never its parent story/Spec |

**Repo:** `finding.repo` (not necessarily `review_issue.repo`)

**Body sections** (rendered by script):

- Finding metadata (ID, severity, disposition, review date, owner)
- Summary / Evidence / Involved code
- Reproduction (when provided)
- Branches table from input issue
- Linked context (reviewed issue, user story, PR, triage path)
- Recommendation
- Review history (appended on update)

---

## Sync behavior

| Case | Action |
|------|--------|
| CONFIRM, no existing `[RR-NN]` Bug | Create Bug in `finding.repo`, link as sub-issue of **reviewed issue** |
| CONFIRM, existing Bug | Update title/body; append **Review history** |
| TRACK, no existing `[RR-NN]` Task on reviewed issue | Create Task in `finding.repo`, link as sub-issue of **reviewed issue** |
| TRACK, existing Task on reviewed issue | Update title/body; append **Review history** |
| Prior Bug, not CONFIRM this run | Close with reason (DISMISS, re-triaged to TRACK, etc.) |
| Prior Task on reviewed issue, not TRACK this run | Close with reason |
| DISMISS only | No new issue; triage doc records rationale |

---

## Idempotency

Match existing **open** sub-issues by title prefix `[RR-NN]` or body line `**Finding ID:** RR-NN`:

| Pool | Parent | Match kind |
|------|--------|------------|
| Bugs | `review_issue` | `issue_type: Bug`, or `[RR-NN]` + body `**Disposition:** CONFIRM` |
| Tasks | `review_issue` | `issue_type: Task`, or `[RR-NN]` + body `**Disposition:** TRACK` |

When GitHub issue types are missing on sub-issues (GraphQL fallback), matching uses disposition in the issue body. `sync-bugs` emits a **warning** in that case.

| Re-review outcome | Script action |
|-------------------|---------------|
| CONFIRM + no Bug match | Create Bug + `addSubIssue(review_issue)` |
| CONFIRM + open Bug match, same finding | Update Bug + history (same-day re-run replaces that history entry) |
| CONFIRM + closed Bug match, or open Bug with different summary | **Create new** Bug with next free RR-ID; warn; may close superseded open issue |
| TRACK + no Task match | Create Task + `addSubIssue(review_issue)` |
| TRACK + open Task match, same finding | Update Task + history |
| TRACK + closed Task match, or open Task with different summary | **Create new** Task with next free RR-ID; warn; may close superseded open issue |
| Open Bug + not CONFIRM | Close Bug (+ close Task if re-triaged to TRACK) |
| Open Task + not TRACK | Close Task (+ close Bug if re-triaged to CONFIRM) |
| DISMISS | Close reason on stale Bug or Task |
| Duplicate RR-ID on multiple sub-issues | Warning; last indexed sub-issue wins |

Agent-side RR-ID rules: [gh-review-rr-ids.md](gh-review-rr-ids.md).

Run `sync-bugs --dry-run` to preview actions before live publish.

```bash
python3 .cursor/commands/_scripts/gh/gh-review-publish.py sync-bugs \
  --input /tmp/gh-review-payload.json -o /tmp/gh-review-sync.json --dry-run
```

---

## Cross-repo sub-issues

Input issue may live in repo A; Bug/Task in repo B. `addSubIssue` uses global node IDs — supported when `preflight` passes.

---

## Parent comment

Posted on `review_issue` after sync (or **updated in place** when a prior `## gh-review summary` comment exists):

- Aggregate verdict, triage path, user story link
- CONFIRM / TRACK / DISMISS counts
- Bug sync and Task sync counts (created / updated / closed)
- Links to Bug sub-issues and Task sub-issues

Re-running `comment` replaces the existing summary comment instead of appending a second one.

---

## Flat fallback (sub-issues unavailable)

1. Create Bugs/Tasks in defect repos with traceability block pointing to `review_issue` / `story_issue`
2. Comment on input issue listing issue URLs
3. Do **not** silently skip hierarchy — record fallback in triage doc

---

## Example

See [gh-review.example.payload.json](../../examples/gh-review.example.payload.json).

---

## Anti-patterns

- DISMISSing test findings as style/non-blocker instead of TRACK with `test-hygiene` ([gh-review-triage-rules.md](gh-review-triage-rules.md))
- Using `hygiene` or `test-hygiene` as `dismiss_reason` (TRACK only)
- Using DISMISS for spec/hygiene/test-hygiene items that should be TRACK
- Filing TRACK Tasks under the input issue's **parent** (user story, Spec, or epic)
- Filing all issues in the wrong repo when code lives elsewhere
- Omitting `repo` on CONFIRM/TRACK findings (defaults wrong)
- Empty `branches` when input issue has Development branches table
- Skipping `comment` after sync
- Manual `gh issue create` instead of `sync-bugs` (breaks idempotency)
- Creating issues for DISMISS findings
- Restarting RR-IDs at `RR-01` when `rr_id_registry.existing` is non-empty
- Creating duplicate `[RR-NN]` issues on re-review instead of updating
- Omitting prior findings from payload instead of DISMISS (leaves stale issues open)
- Leaving dismissed Bugs/Tasks open
- Triage only in chat with no markdown file
