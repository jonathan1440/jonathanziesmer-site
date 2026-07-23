# gh-plan — Update mode (drift re-plan)

Delta procedure for refreshing task issues after [/gh-update-plan](../../gh-update-plan.md) detects scope drift. Load **only on drift** — not for fresh `/gh-plan` breakdowns.

Invoked from [gh-update-plan-github-procedure.md §Re-plan](gh-update-plan-github-procedure.md#re-plan-drift-only).

---

## When this applies

- `/gh-update-plan` passed the started gate and branch sync
- `pre_story_sha != post_story_sha` and at least one task scope path changed
- Task sub-issues already exist (`manifest.work_issues`)

Do **not** run when the started gate failed or story SHA did not move.

---

## Load

1. [planning-shared.md](planning-shared.md) — context, listed repos, checkouts
2. [gh-plan-research-procedure.md](gh-plan-research-procedure.md) — subagent orchestration (**skip branch sync** in preamble)
3. [plan-minimal-change.md](../lib/plan-minimal-change.md) — task scope discipline
4. [gh-plan-procedure.md](gh-plan-procedure.md) — [Task decomposition](gh-plan-procedure.md#task-decomposition), [Publish payload](gh-plan-procedure.md#publish-payload), [Blocker rules](gh-plan-procedure.md#blocker-rules), [Commands](gh-plan-procedure.md#commands) (`finish-plan`)

**Do not load** [gh-plan.md](../../gh-plan.md) — fresh-plan checklist and gates do not apply.

---

## Differences from fresh `/gh-plan`

| Step | Fresh `/gh-plan` | Update mode |
|------|------------------|-------------|
| Branch sync | Run `--mode plan` before subagents | **Skip** — already done; use `pre_story_sha` / `post_story_sha` from sync JSON |
| Task IDs | Assign new `US-*-TASK-*` | **Preserve** existing ids when the work unit still applies |
| Subagent seed | AC + spec excerpt only | Also pass existing `manifest.work_issues` ids + parsed `## Scope` tables |
| Scope change | — | Subagents must note **why** (moved modules, new dependencies, API shape change) |
| Removed tasks | — | Warn only — do not auto-close (v1) |

---

## Parent checklist

1. **Context** — [planning-shared.md](planning-shared.md); story issue, manifest, listed repos → checkouts
2. **Seed subagents** — per-repo: existing task ids, Scope tables, drifted file hints from update-plan procedure
3. **Subagent research** — parallel readonly `explore`, one per listed repo with checkout (max 6); [gh-plan-research-procedure.md](gh-plan-research-procedure.md)
4. **Merge** — preserve ids where applicable; split or add ids only when research requires it
5. **Blockers** — `gh project item-list`; direct edges only ([procedure §Blocker rules](gh-plan-procedure.md#blocker-rules))
6. **Payload** — [gh-plan.example.publish.json](../../examples/gh-plan.example.publish.json); `types.work`: `"Task"`
7. **`finish-plan`** — agent runs via Shell ([procedure §Commands](gh-plan-procedure.md#commands)); retry on failure
8. **Present** — branches rebased, drifted files, task table (Task ID, Repo, Issue, what changed)

---

## Red flags

- Re-running branch sync (already completed by update-plan)
- Creating new task ids when existing ids still apply
- Auto-closing task issues removed from payload (v1: warn only)
- Loading full [gh-plan.md](../../gh-plan.md) checklist
- Researching repos not on the story issue list

---

## Verification

- [ ] Branch sync was **not** re-run
- [ ] Existing task ids preserved where work units unchanged
- [ ] Subagents documented why scope changed
- [ ] `finish-plan` ran; manifest `work_issues` updated
- [ ] Removed tasks warned, not auto-closed
