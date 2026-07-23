# Planning — shared context

Shared by [/gh-plan](../../gh-plan.md), [/gh-update-plan](../../gh-update-plan.md), and [gh-plan-update-procedure.md](gh-plan-update-procedure.md).

---

## Context resolution

1. `gh issue view <story>` — body (canonical AC, **Repositories touched**), labels, repository
2. Parent spec issue — `Parent spec: #N` in body or GitHub parent/sub-issue graph
3. `gh-spec.manifest.json` — story index, per-story `repos`, project, spec path
4. `SPEC.md` — tech stack and patterns (not canonical AC; **not** used to pick research repos)

---

## Target repos

Research and drift checks run **only** in repositories listed on the input story issue.

**Sources (in order):**

1. `## Repositories touched` table in story issue body
2. `manifest.stories.<US-ID>.repos[].repo`

**Not allowed:** UI/API pairing heuristics, proxy-route discovery, `SPEC.md` cross-repo tables, workspace scans for sibling repos, or defaulting to the story home repo when the list is missing.

If the list is empty, **stop** and ask the user to fix the story issue before continuing.

---

## Local checkout mapping

Map **listed repos only** to workspace paths via script:

```bash
python3 .cursor/commands/_scripts/gh/gh_git_helpers.py resolve-checkouts \
  --repos run-rhino/finish-photos,run-rhino/finish-photos-ui
```

JSON `checkouts` maps `owner/repo` → absolute path or `null`. On ambiguous match the script exits with an error. Do **not** scan other org repos or add repos not on the story list.

Manual fallback: match directory name under `[cwd, parent(cwd)]`; confirm with `git -C <dir> remote get-url origin`.

---

## finish-plan idempotency

`finish-plan` updates existing task issues when `tasks[].id` matches an entry in manifest `work_issues`. Re-run with the same ids to refresh bodies and reconcile blockers.

**Update mode** ([gh-plan-update-procedure.md](gh-plan-update-procedure.md)): preserve `US-*-TASK-*` ids when the work unit still applies; do not auto-close task issues removed from the payload (v1: warn only).
