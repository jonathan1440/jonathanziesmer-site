---
name: gh-review-rr-ids
description: >-
  RR-ID assignment, stability across re-runs, and reconciliation with
  gh-review-publish.py sync output.
---

# gh-review RR-ID rules

RR-IDs are **stable keys** for GitHub sub-issues. The publish script matches `[RR-NN]` on existing sub-issues and **updates** them — it does not create a new ticket when the ID collides.

## Assignment (mandatory)

1. **Before assigning IDs**, read `context.rr_id_registry` and any prior triage doc for this issue.
2. **Same finding as a prior review** → reuse that RR-ID (even if summary wording improves slightly).
3. **New finding** → assign the next free ID: `rr_id_registry.next_id`, then increment locally (`RR-09`, `RR-10`, …).
4. **Fixed / no longer applicable prior finding** → include in payload as **DISMISS** with the **original** RR-ID (closes stale sub-issue; does not overwrite).
5. **Never restart at `RR-01`** when the reviewed issue already has `[RR-NN]` sub-issues unless you are triaging the **same** findings again.

Normalize each finding before triage:

| Field | Value |
|-------|-------|
| `id` | `RR-01`, `RR-02`, … per rules above |
| `severity` | CRITICAL / HIGH / MEDIUM / LOW |
| `path:line` | from subagents |
| `summary` | one line |
| `suggestion` | fix direction |

## Re-run behavior

Safe to run `/gh-review` again on the same issue:

| Step | Re-run behavior |
|------|-----------------|
| `context` | Refreshes `rr_id_registry` from existing sub-issues — **do not restart RR-IDs** |
| `sync-bugs` | Updates open `[RR-NN]` matches; closes stale bugs/tasks; allocates new IDs only when guardrails block overwrite |
| `comment` | **Upserts** the existing `## gh-review summary` comment when present |

After `sync-bugs`, check `warnings` and `requested_id` on results — the script may reallocate an ID when a collision would overwrite a closed issue or a different finding. Update the triage doc to match GitHub.

Stop and reconcile when `sync-bugs` emits `warnings` or `requested_id` reallocations.

**Agent-side:** assign new findings `≥ rr_id_registry.next_id` from `context`. Reuse an RR-ID only when triaging the **same** finding again.

Run `sync-bugs --dry-run` to preview actions before live publish. Read `warnings` and `counts.reallocated` in the sync summary.

**Zero findings:** write short triage note, run `comment` with empty sync summary (or skip sync-bugs), report clean review.

## Anti-patterns

- Creating duplicate `[RR-NN]` issues on re-review instead of updating
- Restarting RR-IDs at `RR-01` when sub-issues already exist (overwrites old tickets)
- Omitting prior findings from payload instead of DISMISS (leaves stale issues open)
- Leaving dismissed Bugs/Tasks open

See [gh-review-github-procedure.md](gh-review-github-procedure.md) §Idempotency for script-side matching rules.
