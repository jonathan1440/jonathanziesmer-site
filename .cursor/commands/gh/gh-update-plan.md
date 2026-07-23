---
name: gh-update-plan
description: Sync spec/story branches and refresh task issues when scope drifted — hard stop if any branch has non-merge implementation commits.
---

# gh-update-plan

Refresh an existing `/gh-plan` breakdown when upstream branches moved, **without** disturbing in-flight implementation.

Load:

1. [gh-update-plan-github-procedure.md](procedures/pipeline/gh-update-plan-github-procedure.md) — always
2. [gh-plan-update-procedure.md](procedures/pipeline/gh-plan-update-procedure.md) — **only when** drift detected (procedure §Scope drift gate)

**Do not duplicate bash, JSON, or procedure detail here.**

## Checklist (parent)

1. **Context** — [planning-shared.md](procedures/pipeline/planning-shared.md)
2. **Started gate** — [procedure §Started gate](procedures/pipeline/gh-update-plan-github-procedure.md#started-gate-required--run-first); hard stop per [branch-sync-procedure.md §Command-specific gates](procedures/pipeline/branch-sync-procedure.md#command-specific-gates)
3. **Branch sync** — [procedure §Branch sync](gh-update-plan-github-procedure.md#branch-sync-not-started-branches-only)
4. **Drift gate** — [procedure §Scope drift gate](gh-update-plan-github-procedure.md#scope-drift-gate)
5. **Re-plan** — [gh-plan-update-procedure.md](procedures/pipeline/gh-plan-update-procedure.md) on drift only
6. **Present** — sync summary via JSON `user_message`, drift `outcome`, or stop reason

## When to use

Task sub-issues exist; spec/story branches from `/gh-spec` + `/gh-plan` with **no non-merge implementation commits** on spec, story, or task branches.

**Invoke when any of these drift triggers apply (outline §2.b, §7.e):**

- A task estimated at ≤2 hours reveals >4 hours of work during implementation
- Completed tasks surface shared dependencies that were not visible at planning time
- Acceptance criteria for the story have changed since planning
- A task has scope-exploded to >2× its original estimate or is blocking multiple other tasks — escalate to the story owner for the re-plan decision before invoking

**Anti-trigger:** Do not re-plan after every task. The original plan is usually good enough; invoke only when the above triggers apply. Document the drift reason when invoking so future plans benefit from the learning.

The mechanical gate (`gh_scope_drift.py`, branch SHA comparison) still governs what the command does once invoked; the triggers above are *reasons to invoke*, not replacements for the branch check.

**When NOT:** Any branch started → command stops (finish work first, or run `/gh-plan` for intentional fresh breakdown).

## Next step

No drift: [/gh-build](gh-build.md) on an unblocked task. After drift re-plan: review updated task issues, then build.
