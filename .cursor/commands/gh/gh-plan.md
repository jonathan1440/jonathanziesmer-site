---
name: gh-plan
description: Hub-and-spoke repo research subagents, then finish-plan to publish task sub-issues. Agent MUST run finish-plan — never hand commands to the user.
---

# gh-plan

GitHub-native task breakdown from a **single issue** (usually a `/gh-spec` user story with AC). Creates layer-3 work sub-issues immediately — no `plan.md`, no approval gate before publish.

Load:

1. [planning-shared.md](procedures/pipeline/planning-shared.md) — context, listed repos, checkout mapping
2. [gh-plan-procedure.md](procedures/pipeline/gh-plan-procedure.md) — branch sync, publish, blockers, payload
3. [gh-plan-research-procedure.md](procedures/pipeline/gh-plan-research-procedure.md) — subagent orchestration for code research
4. [plan-minimal-change.md](procedures/lib/plan-minimal-change.md) — smallest diff / pattern preservation for task scope

**Do not duplicate bash, JSON, or procedure detail here.**

## Checklist (parent)

1. **Context** — [planning-shared.md](procedures/pipeline/planning-shared.md) (story issue, manifest, `SPEC.md`, listed repos → checkouts)
2. **Branch sync** — home repo before subagents ([branch-sync-procedure.md](procedures/pipeline/branch-sync-procedure.md))
3. **Subagent research** — parallel readonly `explore`, one per **listed** repo with checkout (max 6); see [gh-plan-research-procedure.md](procedures/pipeline/gh-plan-research-procedure.md)
4. **Blockers** — `gh project item-list`; build direct `blockers[]` edges ([procedure §Blockers](procedures/pipeline/gh-plan-procedure.md#blocker-rules))
5. **Payload** — JSON per [gh-plan.example.publish.json](examples/gh-plan.example.publish.json); `types.work`: `"Task"` (GitHub issue type, not label `task`)
6. **`finish-plan`** — agent runs via Shell ([procedure §Commands](procedures/pipeline/gh-plan-procedure.md#commands)); retry on failure; never hand off to user
7. **Present** — task URL table (Task ID, Repo, Branch, Issue, Duration, Estimate field, Blockers); story issue + **Implementation notes**

Optional once per session: `python3 .cursor/commands/_scripts/gh/gh-spec-publish.py preflight`

## When to use

- After `/gh-spec` story publish — one story issue at a time
- Any GitHub issue with acceptance criteria **and** an explicit repository list in the issue body
- Cross-repo features when `/gh-spec` recorded multiple repos on the story

**Gate:** No repository list on story issue or manifest → **stop**; ask user to fix via `/gh-spec` re-publish or edit story issue.

## Present output

| Task ID | Repo | Branch | Issue | Duration | Estimate field | Blockers |
|---------|------|--------|-------|----------|----------------|----------|

`Duration` = `duration_estimate` in task body. `Estimate field` = GitHub Project **Estimate** (`finish-plan` sets from same value; hours, `d` → 8h/day). Warn-only if no Estimate field or issue not on board.

Confirm each work issue has type **Task**. Invite edits or re-run (`finish-plan` is idempotent).

## Critical rules

- Subagents for repo research when listed repos have local checkouts
- **Listed repos only** — never discover, pair, or research repos not on the story issue
- **Issue type `Task`** — `types.work` in payload; do not use label `task` or `labels` in payload
- **Collapse ambiguity** — planner locks choices in `decisions[]`; no open `either`/`or`/`consider`/`TBD` left for `/gh-build`
- **Run `finish-plan`** every invocation
- **No `plan.md`**, no production code, no approval gate before creating issues
- Work issues attach to **story issue**, not spec parent
- Subagents: readonly, no nested subagents, no file writes, one listed repo each

## Re-run / stale plans

- Re-run `finish-plan` with same `task.id` values to update bodies and reconcile blockers
- Upstream moved, branches not started → [/gh-update-plan](gh-update-plan.md)
- Branches **started** (non-merge implementation commits) → `/gh-update-plan` hard-stops; use `/gh-plan` re-run only for intentional fresh breakdown

## Next step

[/gh-build](gh-build.md) on an unblocked task issue (one at a time).
