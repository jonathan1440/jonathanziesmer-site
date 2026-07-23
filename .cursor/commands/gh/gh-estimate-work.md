---
name: gh-estimate-work
description: Bottom-up hour estimates for a GitHub issue and its sub-issues; rolls up parent Estimate as sum of children on the Planning project. Use when estimating spec parents, user stories, or tasks; reconciling Planning board Estimate fields; or before /gh-plan when story-level targets are needed.
---

# gh-estimate-work

Produce **bottom-up hour estimates** for a GitHub issue and its sub-issues, then set GitHub Project **Estimate** fields so **parent = sum(children)**.

Load **[gh-estimate-work-procedure.md](procedures/pipeline/gh-estimate-work-procedure.md)** — required rubric, subagent rules, rollup, and apply contract.

## When to use

- After `/gh-spec` publish — estimate User Story sub-issues under a Spec parent
- Before `/gh-plan` — story-level hour targets when tasks do not exist yet
- Reconcile Planning board **Estimate** when parent guess ≠ sum of children
- Single **User Story** or **Task** without children

## Inputs

| Input | Required | Example |
|-------|----------|---------|
| GitHub issue | Yes | `https://github.com/run-rhino/finish-photos/issues/90` |
| Parent hour target | No | "stay near 40h" — adjust largest uncertain rows to converge |
| Manifest | No | `docs/specs/<slug>/gh-spec.manifest.json` (project + story index) |
| Apply after estimate | No | Default: present table, wait for approval, then apply |

## Mandatory execution (parent)

**You MUST run `apply-estimates` yourself** after user approval. Do not hand commands to the user.

### Sequence

1. **`gh issue view`** — input issue; note `Parent spec:`, repositories, project
2. **Sub-issues** — `gh api repos/{owner}/{repo}/issues/{n}/sub_issues`
3. **Context** — `SPEC.md`, manifest, archived `*work-estimates*` if present
4. **Scope gate** — parent notes vs story AC; stop if conflict is unresolved
5. **Subagent research** — parallel `explore` per listed repo (procedure); skip if single task with obvious scope
6. **Score each child** — procedure rubric; half-day buckets
7. **Roll up** — sum children; reconcile to user target within ~15%
8. **Present table** — issue, title, hours, rationale, rollup delta
9. **Approval** — wait unless user said to apply immediately
10. **Write payload** — e.g. `/tmp/gh-estimate-work-payload.json`
11. **Apply**:

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py apply-estimates \
  --input /tmp/gh-estimate-work-payload.json \
  --manifest-path docs/specs/<slug>/gh-spec.manifest.json
```

`--manifest-path` is optional when payload includes `project` and issues are already on the board.

12. **Confirm** — re-read Estimates via `gh issue view` project fields or present apply script output table

### Dry run

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py apply-estimates \
  --input /tmp/gh-estimate-work-payload.json \
  --dry-run
```

## Present output

After estimation (and after apply when run):

| Issue | Title | Hours | Estimate field | Rationale |
|-------|-------|-------|----------------|-----------|

Footer: **Children total** · **Parent Estimate** · **Delta**

Invite edits; re-run apply with updated payload (idempotent field updates).

## Critical rules

- **Parent = sum(children)** on the project board unless user explicitly keeps parent as a separate cap
- **Half-day buckets** — avoid false precision before `/gh-plan` task breakdown
- **Priors first** — map archived task estimates to current stories before inventing numbers
- **Scope conflicts** — parent issue notes vs AC: resolve before locking hours
- **Subagents for code-backed estimates** — readonly `explore`, one repo per subagent, max 6
- **No production code** in the same invocation
- **Approval before apply** — unless user requests immediate write
- Task-level estimates from `/gh-plan` should sum to story Estimate; re-run this command if they diverge materially

## Relationship to `/gh-plan`

| Stage | Estimate lives on |
|-------|-------------------|
| After `/gh-spec` | User Story issues (this command) |
| After `/gh-plan` | Task issues (`duration_estimate` → Estimate via `finish-plan`) |

Story Estimate ≈ sum(task Estimates). If tasks reveal a gap, update story + parent via `apply-estimates`.

## Example payload

See [gh-estimate-work.example.payload.json](examples/gh-estimate-work.example.payload.json).
