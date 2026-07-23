# Branch sync — shared procedure

Operational contract for rebasing spec and story branches before `/gh-plan` research or `/gh-update-plan` drift checks. Loaded by [gh-plan-procedure.md](gh-plan-procedure.md) and [gh-update-plan-github-procedure.md](gh-update-plan-github-procedure.md).

**Agent runs the sync script via Shell — not the user.**

---

## When to run

- **Home repo** checkout only for rebase steps (manifest `repo` — where the story issue lives)
- **Before** research subagents (`/gh-plan`) or drift detection (`/gh-update-plan`)
- Requires manifest `spec_branch`, `feature_slug`, and `stories.<US-ID>.branch`

Branch names from manifest:

- `spec_branch` — e.g. `spec/csv-fallback-staff-ui`
- `stories.<US-ID>.branch` — e.g. `user-story/US-01-upload-results-csv`
- `feature_slug` — spec-not-started path filter (`docs/specs/<slug>/`)

---

## Started semantics

**Started** (both commands) = at least one **non-merge commit** in the relevant range representing original work — not replayed upstream history. Merge commits from rebasing default → spec or spec → story **do not** count.

| Branch | Started when |
|--------|----------------|
| **Spec** | Any non-merge commit on `origin/<default>..origin/<spec_branch>` touches files **outside** `docs/specs/<feature_slug>/` |
| **Story** | `rev-list --no-merges --count origin/<spec_branch>..origin/<story_branch>` > 0 |
| **Task** (`/gh-update-plan` only) | Non-merge commits on task branch ahead of story/spec merge-base — see script with `--mode update-plan` |

---

## Sync command

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py sync-plan-branches \
  --manifest-path docs/specs/<slug>/gh-spec.manifest.json \
  --story-id US-01 \
  --repo-path /path/to/home-repo \
  [--mode plan|update-plan] \
  [--other-repo run-rhino/finish-photos-ui:/path/to/ui] \
  [--dry-run]
```

**JSON result fields:**

| Field | Meaning |
|-------|---------|
| `status` | `"ok"` when sync completed |
| `blocked_reason` | `branch_started`, `implementation_in_progress`, or `rebase_conflict` |
| `require_user_confirm` | `true` when `/gh-plan` must stop and ask user (started branch) |
| `started_branches` | Table rows: kind, branch, repo, non_merge_count, sample_shas |
| `pre_story_sha` / `post_story_sha` | For `/gh-update-plan` drift gate (`check-scope-drift`) |
| `user_message` | Rendered stop/confirm text when `blocked_reason` is set |
| `actions` | Rebases, pushes, branch creates performed |
| `conflicts` | Paths when `blocked_reason` is `rebase_conflict` |
| `other_repos` | Fetch/checkout results for `--other-repo` checkouts |

Exit code **0** = proceed; **2** = blocked (interpret `blocked_reason`).

### Script behavior (home repo)

1. `git fetch` default, spec, story (when remote exists)
2. Run started checks (spec, story; tasks when `--mode update-plan`)
3. If started → return blocked JSON (no rebase)
4. If spec not started and default ahead → rebase spec onto default, `push --force-with-lease`
5. If story not started:
   - Remote missing → create story branch from spec tip, push
   - Spec ahead of story → rebase story onto spec, `push --force-with-lease`
6. For each `--other-repo` → `git fetch`; checkout story branch, else spec branch

---

## Command-specific gates

| Command | When `blocked_reason` is set |
|---------|------------------------------|
| **`/gh-plan`** (`--mode plan`) | `branch_started` → stop; present `user_message` (or `render-message --template branch-started-confirm`); proceed **only** if user explicitly confirms. `rebase_conflict` → present `user_message`; do not research on dirty tree. |
| **`/gh-update-plan`** (`--mode update-plan`) | Any started branch → **hard stop**. Present `user_message`. Do not rebase, drift-check, or re-plan. |

`/gh-update-plan` records `pre_story_sha` and `post_story_sha` from JSON for the drift gate.

---

## Manual fallback

Use only when the script is unavailable. Same semantics as above:

```bash
DEFAULT=$(gh repo view "$HOME_REPO" --json defaultBranchRef -q .defaultBranchRef.name)
git -C "$REPO_PATH" fetch origin "$DEFAULT" "$SPEC_BRANCH" "$STORY_BRANCH"
# spec started: log origin/$DEFAULT..origin/$SPEC_BRANCH --no-merges --name-only | grep -v ^docs/specs/$SLUG/
# story started: rev-list --no-merges --count origin/$SPEC_BRANCH..origin/$STORY_BRANCH
# rebase spec → push --force-with-lease; rebase story or create from spec tip
```

---

## Red flags

- Rebasing when started checks fail
- Research on a conflicted or dirty tree
- Skipping sync when manifest has `spec_branch` and story `branch`
- Auto-rebase in non-home listed repos without the same not-started checks
