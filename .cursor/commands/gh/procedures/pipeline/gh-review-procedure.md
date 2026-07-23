---
name: gh-review-procedure
description: >-
  Procedure for GitHub-issue-scoped review, CONFIRM/TRACK/DISMISS triage,
  markdown triage artifact, Bug sub-issue sync under the reviewed issue,
  and Task sub-issue sync under the reviewed issue via gh-review-publish.py.
---

# gh-review procedure

## Overview

1. **Context** — script gathers issue graph, PRs, branches, scope hints, `story_issue`
2. **Review** — mandatory parallel subagents + five-axis synthesis ([gh-review-review-synthesis.md](gh-review-review-synthesis.md)), then harness re-run (scoped tiers) and contract sign-off (Phases 2b–2c)
3. **Triage** — evidence-first CONFIRM / TRACK / DISMISS ([gh-review-triage-rules.md](gh-review-triage-rules.md))
4. **Publish** — script creates/updates/closes Bug + Task sub-issues; parent comment ([gh-review-github-procedure.md](gh-review-github-procedure.md))

Do **not** implement fixes unless the user explicitly asks in the same turn.

---

## Phase 0 — Context (script)

```bash
python3 .cursor/commands/_scripts/gh/gh-review-publish.py preflight
python3 .cursor/commands/_scripts/gh/gh-review-publish.py context \
  --issue <URL-or-OWNER/REPO#N> -o /tmp/gh-review-context.json
```

Read `/tmp/gh-review-context.json`:

| Field | Use |
|-------|-----|
| `review_issue` | Input issue (parent for new **Bug** and **Task** sub-issues) |
| `story_issue` | Linked user story for AC/context in finding bodies — **not** the Task sub-issue parent |
| `parent_issues` | Epic/spec ancestors; traceability only |
| `sub_issues` | Existing bugs/tasks on reviewed issue — dedupe, don't re-file |
| `rr_id_registry` | Reserved RR-IDs: `existing[]`, `max_number`, `next_id` — **start new IDs here** |
| `linked_prs` | Primary review target when present |
| `branches` | Diff base when no PR; copy into synced issue bodies |
| `scope_hints` | `repos_touched`, `spec_path`, `manifest_path`, `story_issue_number` |

**Load scope anchors** before judging findings:

- Parent issue body + `SPEC.md` (from `scope_hints.spec_path`)
- `gh-spec.manifest.json` when present
- Story AC on input or parent story sub-issue
- Sibling sub-issues for overlap
- Prior `gh-review-*.md` triage doc for the same issue (when re-reviewing)
- `rr_id_registry.existing` — **do not reuse RR-IDs for different findings**

Write a **Scope reminder** (bullets: in scope / out of scope) for the triage doc header.

Optionally scaffold triage doc early:

```bash
python3 .cursor/commands/_scripts/gh/gh-review-publish.py init-triage-doc \
  --context /tmp/gh-review-context.json
```

---

## Phase 1 — Resolve review target

Priority (first usable wins):

1. **Linked PR** (`linked_prs[0]`) — fetch diff at head ref (`gh pr diff`, read full files at head)
2. **Branch** from `branches` or `gh issue develop --list` — diff vs `base` or story/spec parent branch
3. **Task file scope** — paths listed on a task sub-issue body
4. **Explicit paths** in issue body — weakest; read at branch HEAD or default branch

Resolve via script (or record equivalent working notes):

```bash
python3 .cursor/commands/_scripts/gh/gh-review-publish.py resolve-target \
  --context /tmp/gh-review-context.json -o /tmp/gh-review-target.json
```

PR is **context**, not required. When a PR exists, cite it in triage and payload `pr` block.

**Gate:** If `resolve-target` returns `"type": "none"` → stop and ask. Do not review without a target.

---

## Phase 2 — Review (mandatory subagents)

Follow [gh-review-review-synthesis.md](gh-review-review-synthesis.md). Assign RR-IDs per [gh-review-rr-ids.md](gh-review-rr-ids.md).

---

## Phase 2b — Harness re-run (scoped tiers)

Re-run the testing harness from the review target checkout (PR head or branch), scoped to the review level (outline §3, §4.4.a.6):

| Review level | Tiers | Command |
|--------------|-------|---------|
| **Task** issue | 1–4 | `bash scripts/test-tiers.sh 4` |
| **Story / spec** issue | 1–6 | `bash scripts/test-tiers.sh 6` |

Rules:

- Tiers run in order; the runner stops at the first real failure. Tier `exit 2` = skipped (no tooling/surface), not a failure.
- Each failing tier becomes a **finding**: assign an RR-ID, triage in Phase 3 like any reviewer finding (tier failures are normally CONFIRM; severity per [gh-review-triage-rules.md](gh-review-triage-rules.md)).
- **Story/spec level — tier 6 judge:** drive the product surface with the `product-judge` subagent ("testing agent as customer" — would this delight the target user?). The judge determines the tier-6 test plan and may direct writing or revising `scripts/test-tier6-local.sh` during the loop; hardcoded scripts the agent cannot modify defeat the purpose. Judge failures become findings like any other.
- No human triggers a tier — the agent owns this loop.

---

## Phase 2c — Contract sign-off (exit criterion)

Spawn the `contract-reviewer` subagent (mandatory, every review level). Give it:

- The diff / review target from Phase 1
- Story AC (`story_issue`, `scope_hints.spec_path` → `SPEC.md` and the story doc under `docs/user-stories/`)
- The repo's `AGENTS.md` architectural contract

It returns **SIGN-OFF** or **REJECT** with per-AC and per-contract-rule results. REJECT reasons become findings (RR-IDs, triaged in Phase 3). Record the verdict in the triage doc header and the parent comment.

**Machine-checked gate (Phase 5):** also write a structured `contract_signoff` object into the sync-bugs payload:

```json
{
  "verdict": "SIGN-OFF",
  "head_sha": "<current PR head SHA>",
  "reviewed_at": "<ISO-8601>"
}
```

The dispatcher will not request human review (and will not treat the change as Ready to ship) unless `verdict == SIGN-OFF` and `head_sha` still equals the live PR head. Any resolve commit that moves HEAD invalidates the prior SIGN-OFF — re-run contract review within the cycle budget.

**Risk class (Phase 5):** classify the PR against `AGENTS.md` change categories (`normal` | `design_conversation`) and set `risk_class` on the payload. `design_conversation` hard-stops further dispatcher chaining until a human clears the latch.

**Merge confidence bar (outline §3 exit criterion):** scoped tiers passing **+** contract sign-off. Neither alone is sufficient for a high-confidence merge recommendation.

---

## Phase 3 — Triage (CONFIRM / TRACK / DISMISS)

Apply [gh-review-triage-rules.md](gh-review-triage-rules.md) to every RR-ID.

### Subagent assignment (required when ≥3 findings)

Load [triage-surface-area-groups.md](triage-surface-area-groups.md). Each subagent returns per finding: **disposition**, rationale, evidence, `owner_sa` (use CONFIRM / TRACK / DISMISS in prompts, not research-issues labels).

**Subagent prompt:** [triage-subagent-prompt.txt.template](../../../_templates/gh-review/triage-subagent-prompt.txt.template) — set `{{DISPOSITION_ENUM}}` to `CONFIRM | TRACK | DISMISS`.

Parent merges conflicts, spot-checks CONFIRM/TRACK rows, ensures every RR-ID appears exactly once.

### Repo per finding

Set `finding.repo` to the repository containing the primary work path:

- Map local path → `git remote` checkout matching `scope_hints.repos_touched`
- Default to PR repo or `review_issue.repo` only when path is unambiguous

### Triage markdown

Scaffold and fill per [gh-review-triage-doc.md](gh-review-triage-doc.md) (`init-triage-doc` after context).

---

## Phase 4 — Publish (script)

Scaffold payload from context, fill `findings[]` and `aggregate_verdict`, validate, then publish:

```bash
python3 .cursor/commands/_scripts/gh/gh-review-publish.py init-payload \
  --context /tmp/gh-review-context.json -o /tmp/gh-review-payload.json
# … agent fills findings[] from triage …
python3 .cursor/commands/_scripts/gh/gh-review-publish.py validate-payload \
  --input /tmp/gh-review-payload.json
python3 .cursor/commands/_scripts/gh/gh-review-publish.py check-consistency \
  --input /tmp/gh-review-payload.json
python3 .cursor/commands/_scripts/gh/gh-review-publish.py publish \
  --input /tmp/gh-review-payload.json -o /tmp/gh-review-sync.json
```

Inspect sync output **`warnings`** and any result with **`requested_id`**. Fix triage markdown if IDs diverged. Reconcile per [gh-review-rr-ids.md](gh-review-rr-ids.md).

Payload schema: [gh-review.payload.schema.json](../../../_templates/gh-review/gh-review.payload.schema.json). Example: [gh-review.example.payload.json](../../examples/gh-review.example.payload.json). Sync behavior: [gh-review-github-procedure.md](gh-review-github-procedure.md).

---

## Phase 5 — Reply to user

Short summary:

- Input issue link
- User story link (when `story_issue` present in context)
- Harness result (tiers run, pass/skip/fail) + contract sign-off verdict
- Aggregate verdict + CONFIRM / TRACK / DISMISS counts
- Triage markdown path
- Table: RR-ID → Bug or Task URL (created / updated / closed)
- Offer `/gh-resolve-issues` only if asked

---

## Quality bar

- [ ] `context` script run before review
- [ ] consider-reviewing parallel Tasks ran (unless user skipped)
- [ ] Harness re-run at the scoped tier level (task 1–4, story/spec 1–6); failures filed as findings
- [ ] `contract-reviewer` sign-off recorded (verdict in triage doc + parent comment)
- [ ] Every RR-ID triaged with evidence, not vibe ([gh-review-triage-rules.md](gh-review-triage-rules.md))
- [ ] RR-ID rules satisfied ([gh-review-rr-ids.md](gh-review-rr-ids.md))
- [ ] CONFIRM bugs filed in **correct repo**, type **Bug**, parent = reviewed issue
- [ ] TRACK tasks filed under **reviewed issue** (`review_issue` — the input issue, never its parent)
- [ ] Branches from input issue copied into synced issue bodies
- [ ] Triage markdown written; parent issue commented
- [ ] No fix commits unless user requested

## Anti-patterns

See [gh-review-github-procedure.md](gh-review-github-procedure.md) §Anti-patterns, plus:

- Skipping subagents because the issue is "small"
- Implementing fixes during gh-review without user request
