# gh-update-plan — GitHub procedure

Operational contract for `/gh-update-plan`. Load with [gh-update-plan.md](../../gh-update-plan.md).

Reuses [branch-sync-procedure.md](branch-sync-procedure.md). **Differs on started branches:** hard stop — no rebase, no drift check, no re-plan ([§Command-specific gates](branch-sync-procedure.md#command-specific-gates)).

---

## Prerequisites

Same as [gh-plan-procedure.md §Prerequisites](gh-plan-procedure.md#prerequisites), plus:

- Task sub-issues already exist for the story (`manifest.work_issues` or open task sub-issues)
- Original `/gh-plan` has run at least once for this story

---

## Inputs

| Input | Required | Example |
|-------|----------|---------|
| `story_issue` | Yes | User story URL or `run-rhino/finish-photos#20` |
| `manifest_path` | No | Resolved from parent spec / `SPEC.md` frontmatter |

Resolve context per [planning-shared.md §Context resolution](planning-shared.md#context-resolution).

---

## Started gate (required — run first)

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py sync-plan-branches \
  --manifest-path docs/specs/<slug>/gh-spec.manifest.json \
  --story-id US-01 \
  --repo-path /path/to/home-repo \
  --mode update-plan
```

If exit code **2** or `blocked_reason: implementation_in_progress`:

1. Present `user_message` from JSON (or `render-message --template started-gate-stop --input sync.json`)
2. **Exit** — do not rebase, drift-check, or re-plan
3. Do **not** ask to proceed anyway (unlike `/gh-plan` — no user override)

Started semantics: [branch-sync-procedure.md §Started semantics](branch-sync-procedure.md#started-semantics).

---

## Branch sync (not-started branches only)

When the started gate passes, the same command performs rebases and returns `pre_story_sha` / `post_story_sha`. JSON fields and conflict handling: [branch-sync-procedure.md](branch-sync-procedure.md).

If `blocked_reason: rebase_conflict` → present `user_message` and stop.

---

## Scope drift gate

Run **only when** `pre_story_sha != post_story_sha`:

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py check-scope-drift \
  --manifest-path docs/specs/<slug>/gh-spec.manifest.json \
  --story-id US-01 \
  --pre-story-sha "$PRE_STORY_SHA" \
  --post-story-sha "$POST_STORY_SHA" \
  --repo-path /path/to/home-repo \
  --other-repo run-rhino/finish-photos-ui:/path/to/ui
```

**Agent interprets JSON:**

| `outcome` | Exit | Action |
|-----------|------|--------|
| `unchanged` | 0 | Present `user_message`; stop |
| `synced_valid` | 0 | Present `user_message`; stop |
| `drift` | 2 | Present `user_message`; continue to **Re-plan** |

Scope paths: manifest `work_issues.files[]` with task-issue `## Scope` fallback (unless `--no-fetch-issues`). Home repo uses `pre_story_sha..post_story_sha`; other listed repos use `origin/spec..origin/story`.

---

## Re-plan (drift only)

Load [gh-plan-update-procedure.md](gh-plan-update-procedure.md). Do not run when the started gate failed.

---

## Red flags

- Rebasing when started gate failed
- Offering user override on started branches (hard stop only)
- Manual `git diff` loops instead of `check-scope-drift`
- Running drift check when story SHA did not move
- Running full research when `outcome` is `synced_valid`
- Creating new task ids when existing ids still apply
- Auto-closing task issues removed from payload (v1: warn only)
- Skipping task-branch started check when `work_issues` exist
- Researching repos not listed on the story issue

---

## Verification

- [ ] `sync-plan-branches --mode update-plan` ran before any manual git work
- [ ] `user_message` presented when sync blocked or drift check completes
- [ ] `check-scope-drift` skipped when story tip unchanged
- [ ] [gh-plan-update-procedure.md](gh-plan-update-procedure.md) loaded only when `outcome` is `drift`
- [ ] `finish-plan` only when drift detected
- [ ] Manifest `work_issues` updated after re-plan
