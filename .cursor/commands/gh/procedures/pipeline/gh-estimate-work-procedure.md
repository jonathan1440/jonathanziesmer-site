# gh-estimate-work — estimation procedure

Hours on the GitHub Project **Estimate** field (numeric hours). Same unit as `/gh-plan` `duration_estimate` (`3h` → `3`).

## Issue levels

| Input issue type | Sub-issues to estimate | Parent rollup |
|------------------|------------------------|---------------|
| **Spec** (parent) | User Story children | Parent **Estimate** = sum(story hours) |
| **User Story** | Task children if `/gh-plan` published; else estimate the story itself | Story **Estimate** = sum(task hours) or single story hours |
| **Task** | None | Set **Estimate** on the task only |

Resolve type from GitHub issue type or body (`Parent spec: #N`, `## User story`, `## Task`).

## Mandatory parent sequence

1. **Resolve input** — `gh issue view <url>`; repo, number, title, body, project items
2. **List children** — `gh api repos/{owner}/{repo}/issues/{n}/sub_issues --jq '.[] | {number, title}'`
3. **If no children** — treat input as the work unit (single-row estimate)
4. **Resolve context** — parent spec link, `docs/specs/<slug>/SPEC.md`, `gh-spec.manifest.json`, `## Repositories touched` on stories
5. **Find priors** — `docs/specs/<slug>/`, `.archived/**/*work-estimates*.md`, `.archived/**/plan-*.md` in home repo
6. **Scope conflicts** — parent issue notes vs story AC; **stop and ask** if they diverge materially (±6h+ swing)
7. **Research (subagents)** — when children touch code: parallel readonly `explore` subagents, **one per repo** listed on stories or manifest (max 6); parent merges complexity signals only
8. **Bottom-up hours** — per child using scoring rubric below; half-day buckets (2, 3, 4, 5, 6, 8)
9. **Roll up** — `S = sum(children)`; compare to parent target if user gave one; adjust largest uncertain rows to converge within ~15%
10. **Present table** — issue #, title, hours, short rationale; show `S` and parent target delta
11. **User approval** — do not call `apply-estimates` until user confirms (or explicitly says to apply)
12. **Apply** — write payload JSON, run `apply-estimates` (parent runs script; never hand off)

## Scoring rubric (per child)

| Factor | Signal |
|--------|--------|
| Surface area | Repos touched, new modules vs extend existing patterns |
| AC count | More scenarios → more tests, not always more code |
| Integration risk | CDK/IAM, batched + monolithic worker paths, async UI stale requests |
| Contract work | OpenAPI freeze — front-loaded, reduces rework |
| Verification | Staging operator run, visual QA, external dependency (client assets) |

Embed buffers **inside** the child row (staging deploy, visual QA, Dropbox timeout edge cases) — not a mystery parent fudge.

## Subagent research (when required)

**Required** when estimating Spec or User Story children that have `## Repositories touched` or manifest `repos`, and local checkouts exist.

| Who | Work |
|-----|------|
| **Subagent (per listed repo)** | semble search for similar implementations, touch-map files, test patterns, integration surfaces |
| **Parent** | repo list, priors mapping, rubric scoring, rollup, payload write, `apply-estimates` |

Subagents: `readonly: true`, `subagent_type: explore`, no nested subagents, no file writes.

**Prompt must return:**

```markdown
## Repo: owner/name
### Similar patterns
- path — one line
### New / high-risk surfaces
- ...
### Suggested hour range for this repo's share
- low–high h — reason
```

## Prior mapping

When `.archived/**/work-estimates.md` or task tables exist, map rows → current story IDs before inventing new numbers. Adjust for spec drift (e.g. removed admin CRUD, simplified UI).

## Output table (present to user)

| Issue | Title | Hours | Rationale |
|-------|-------|-------|-----------|
| #96 | US-01: … | 6 | Preview API + OpenAPI + unit tests |

**Rollup:** children **28h** · parent target **28h** · delta **0h**

## Apply payload

Write JSON (see [gh-estimate-work.example.payload.json](../../examples/gh-estimate-work.example.payload.json)):

```json
{
  "project": { "owner": "run-rhino", "number": 3 },
  "parent": { "repo": "run-rhino/finish-photos", "number": 90, "hours": 28 },
  "items": [
    { "repo": "run-rhino/finish-photos", "number": 96, "hours": 6 }
  ]
}
```

- `parent` optional when estimating a single issue with no children (omit or set same issue as sole `items` row)
- `project` optional if manifest `project` or issue already on a board; script resolves from manifest when `--manifest-path` passed
- `items[].hours` must be positive numbers

**Validation:** `parent.hours` must equal `sum(items.hours)` within `0.01` unless `--allow-rollup-drift` (warn-only mode).

## Optional issue body note

After apply, parent may append/replace `## Estimate rollup` on the spec issue (idempotent):

```markdown
## Estimate rollup

| Story | Issue | Hours |
|-------|-------|-------|
| US-01 | #96 | 6 |

**Total:** 28h (sum of story Estimates on Planning #3)
```

Only when user asks to persist rationale on the issue.
