# gh-spec — GitHub publish procedure

Parent orchestrator for `/gh-spec` and `gh-spec-driven-development`. **Publish to GitHub only after** the user approves stories, AC, and the complete technical spec.

Script: `.cursor/commands/_scripts/gh/gh-spec-publish.py`

Load this file when the agent reaches **Phase 1.5: Publish** (see `gh-spec-driven-development.md`). Branch sections are also linked from Phase 0 and pre-publish steps.

---

## Prerequisites

```bash
gh --version          # ≥ 2.40 recommended
gh auth status
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py preflight
```

**Project scope:** When the payload includes a `project`, the script auto-refreshes OAuth `project` scope — **complete the device flow** when prompted. Manual: `gh auth refresh -h github.com -s project`.

If `preflight` reports `sub_issues: unavailable`, publish uses **flat fallback** (documented below).

---

## Inputs (collect before publish)

| Input           | Required                                           | Example                                                                            |
| --------------- | -------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `repo`          | Yes (default: `gh repo view --json nameWithOwner`) | `run-rhino/finish-photos`                                                          |
| `feature_slug`  | Yes                                                | `csv-fallback-staff-ui`                                                            |
| `feature_title` | Yes                                                | `CSV fallback for staff UI`                                                        |
| `project`       | Yes                                                | `"Roadmap"` or `run-rhino#3` or project URL                                        |
| `spec_path`     | Yes                                                | `docs/specs/csv-fallback-staff-ui/SPEC.md`                                         |
| `branch`        | Set by publish script                              | `spec/<feature_slug>` — manifest `spec_branch`                                     |
| `types`         | Yes (default applied if omitted)                   | `{ "parent": "Spec", "story": "User Story" }` — GitHub **issue types**, not labels |

---

## Issue types (not labels)

| Layer                       | Issue type     |
| --------------------------- | -------------- |
| Parent spec issue           | **Spec**       |
| Story sub-issue             | **User Story** |
| Task sub-issue (`/gh-plan`) | **Task**       |

Publish payload: `types` only (no `labels` key). Shape: [gh-spec.example.publish.json](../../examples/gh-spec.example.publish.json).

---

## Branch bootstrap (scripted)

Branch names match the publish script: `spec/<feature_slug>`, `user-story/<US-ID>-<story-slug>` (see `spec_branch_name` / `story_branch_name` in `gh-spec-publish.py`).

**Local checkouts:** pass `--workspace-root` (repeatable) and/or `--repo-path` for the home repo. The script scans workspace roots for directories whose `origin` matches `owner/repo` (same rules as [gh-plan-procedure](gh-plan-procedure.md) **Local checkout mapping**).

### Home repo (early, before SPEC.md writes)

Confirm `git rev-parse --show-toplevel` is the project repo, not `~/.cursor`:

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py init-spec-artifacts \
  --slug csv-fallback-staff-ui \
  --title "CSV fallback for staff UI" \
  --repo-path /path/to/checkout \
  --repo OWNER/REPO \
  --bootstrap
```

Equivalent branch-only bootstrap:

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py bootstrap-spec-branch \
  --repo OWNER/REPO \
  --slug csv-fallback-staff-ui \
  --repo-path /path/to/checkout
```

All `docs/specs/<slug>/` edits happen on `spec/<slug>` in the home repo. Template: [SPEC.md.template](../../../../../docs/specs/SPEC.md.template).

### All affected repos (after user approves repo mapping)

After spec + repo table approval — every repo in `affected_repos`:

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py bootstrap-spec-branches \
  --input publish-payload.json \
  --workspace-root /path/to/workspace \
  --push
```

Home repo holds `SPEC.md`; other repos get an empty spec branch tip from default.

### Before publish — commit and push home repo

Commit spec artifacts on `spec/<slug>` (user commit rules apply), then push. The script does **not** commit for you.

### During publish — issue ↔ branch linking (home repo)

`publish` / `finish-spec` link parent and story issues via `gh issue develop` in the **home repo** when `preflight` reports `linked_branches: supported`. Do not run manual linking when publish succeeds without branch-link warnings.

If linking failed, run **link-branches** (below) or see failure recovery.

### Story branches (after publish)

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py bootstrap-story-branches \
  --manifest-path docs/specs/$SLUG/gh-spec.manifest.json \
  --workspace-root /path/to/workspace \
  --push
```

Use `--story US-01` to limit to one story. Non-home repos do not use `gh issue develop` — branches appear in issue **Development branches** tables.

### Manual issue linking (fallback)

When automatic linking failed:

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py link-branches \
  --manifest-path docs/specs/$SLUG/gh-spec.manifest.json \
  --repo "$HOME_REPO"
```

**Implementation PRs:** open story PRs against `spec/<slug>`, not the default branch.

---

## Per-story repositories

Each user story issue is created in the **home repo** (`repo` on the publish payload). Stories may span other repositories.

**When to identify:** during technical spec writing (after AC approval), before publish. Present per-story repo table **and** deduplicated `affected_repos` for user approval.

| Rule                 | Detail                                                              |
| -------------------- | ------------------------------------------------------------------- |
| Home repo            | Always hosts the story **issue** (`payload.repo`)                   |
| `repos` per story    | Every repo that needs implementation work for that story            |
| Roles                | Optional short label per repo                                       |
| Cross-repo           | List each repo explicitly; do not rely on `/gh-plan` to infer later |

Shape: [gh-spec.example.publish.json](../../examples/gh-spec.example.publish.json). Parent `repos` may be omitted — publish derives the union from stories.

**SPEC.md story index** — **Repositories** column before publish; `update-spec` fills issue links after publish.

**Downstream:** `/gh-plan` researches **only** repos listed on the story issue — no repo discovery.

---

## Manifest schema (`gh-spec.manifest.json`)

Written beside the spec. Shape: [gh-spec.example.manifest.json](../../examples/gh-spec.example.manifest.json).

**`status` values:** `partial`, `complete`, `plan_published`.

---

## Publish payload

Do **not** author issue markdown manually. Build JSON; the script renders bodies and writes the manifest.

**Shape:** [gh-spec.example.publish.json](../../examples/gh-spec.example.publish.json)

| Payload field | Issue output |
|---------------|--------------|
| `feature_title`, `spec_path`, `branch` | Parent **Spec artifact** |
| `parent.objective_summary` | **Objective** |
| `repos` (root or union from stories) | **Affected repositories** + **Development branches** |
| `stories[].story_line`, `acceptance_scenarios` | **User story** + **Acceptance scenarios** |
| `stories[].repos` | **Repositories touched** + **Development branches** |
| `types` | GitHub issue types |

---

## Commands (agent sequence)

After user approves spec and repo mapping:

1. **`verify-spec`** — required before publish (`finish-spec` also runs this)

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py verify-spec \
  --spec-path "docs/specs/$SLUG/SPEC.md" \
  --input publish-payload.json
```

2. Commit spec artifacts on `spec/<slug>` in the home repo (user commit rules)
3. `bootstrap-spec-branches --push` → **All affected repos**
4. Build publish payload JSON
5. **`finish-spec`** (preferred) or manual preflight → publish → verify → story branches → update-spec

### finish-spec (preferred)

Runs: `verify-branches` → `publish` → `verify` → `bootstrap-story-branches --push` → `link-branches` → `update-spec` → parent comment.

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py finish-spec \
  --repo "$REPO" \
  --input publish-payload.json \
  --manifest-path "docs/specs/$SLUG/gh-spec.manifest.json" \
  --spec-path "docs/specs/$SLUG/SPEC.md" \
  --workspace-root /path/to/workspace \
  --repo-path /path/to/home/checkout
```

Use `--skip-story-branches` to defer story branch creation. Use `--dry-run` on `publish` only via manual steps below.

### Manual steps (debug / partial runs)

**Preflight**

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py preflight
```

**Verify remotes before publish**

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py verify-branches \
  --input publish-payload.json
```

**Publish (idempotent)**

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py publish \
  --repo "$REPO" \
  --manifest-path "docs/specs/$SLUG/gh-spec.manifest.json" \
  --input publish-payload.json
```

**Verify issues**

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py verify \
  --repo "$REPO" \
  --manifest-path "docs/specs/$SLUG/gh-spec.manifest.json"
```

**Update SPEC.md** (also run by `finish-spec`)

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py update-spec \
  --manifest-path "docs/specs/$SLUG/gh-spec.manifest.json" \
  --spec-path "docs/specs/$SLUG/SPEC.md"
```

**Repair issue types (legacy label publishes)**

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py fix-hierarchy-types \
  --repo "$REPO" \
  --manifest-path "docs/specs/$SLUG/gh-spec.manifest.json"
```

Present parent + story issue URLs; confirm against **Verification (parent, after publish)**.

---

## Flat fallback (no sub-issues)

When `preflight` reports `sub_issues: unavailable`, publish sets `"hierarchy": "flat"`: legacy labels, `Parent: #N` footer on stories, no `addSubIssue`.

---

## Failure recovery

| Failure                            | Recovery                                                                                                           |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `gh issue create` interrupted      | `gh issue create --recover`                                                                                        |
| Parent created, story batch failed | Manifest `status: partial`; re-run `publish` or `finish-spec`                                                        |
| Spec branch missing on remote    | Commit + push home repo, or `bootstrap-spec-branches --push`                                                       |
| Branch linking failed              | `link-branches --manifest-path ...`                                                                                |
| Wrong project                      | `gh project item-add` manually; update manifest `project`                                                          |
| Auth scope                         | Complete device flow when script runs `gh auth refresh`                                                              |

---

## Red flags (orchestrator)

- Creating GitHub issues before user approves stories, AC, or full spec
- Duplicating full AC text in `SPEC.md` after publish (index table only)
- Authoring issue markdown manually — build publish JSON only
- Skipping `verify` after publish
- Putting hierarchy `labels` in the publish payload — use `types` only
- Running git branch loops by hand when script commands exist

---

## Verification (parent, after publish)

- [ ] `preflight` passed (or flat fallback documented)
- [ ] `finish-spec` completed (or publish + verify + update-spec manually)
- [ ] `verify-branches --require-story-branches` exits 0 (when story branches expected)
- [ ] Parent issue references `spec_path` and story index
- [ ] Each `US-*` has a sub-issue (or flat fallback) with full AC text
- [ ] Manifest includes `spec_branch`, top-level `repos`, per-story `branch`
- [ ] `SPEC.md` frontmatter updated (`update-spec`)
- [ ] User confirmed publish output (issue URLs)
- [ ] Parent type **Spec**; each story type **User Story**
- [ ] Home repo: linked `spec/<slug>` on parent and `user-story/...` on each story when linking succeeded
