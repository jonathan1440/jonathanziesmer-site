---
name: gh-spec-driven-development
description: GitHub spec publish workflow for /gh-spec — parent issue, story sub-issues, and docs/specs/<slug>/SPEC.md. Stops after publish; does not plan or implement.
---

# GitHub-native Spec-Driven Development

Loaded by [/gh-spec](../../gh-spec.md). Write a structured spec and publish GitHub issues **before** planning or implementation.

**Scope:** Phases 0–1.5 only. Do **not** invoke [/gh-plan](../../gh-plan.md), [/gh-build](../../gh-build.md), or [/gh-update-plan](../../gh-update-plan.md) during `/gh-spec` — those are separate commands the user runs later.

**Canonical acceptance criteria live in story sub-issues**, not in `SPEC.md`.

User stories and **Given → When → Then** acceptance scenarios are first-class artifacts. Do not skip them for feature work.

## When to Use

- Starting a new project or feature
- Requirements are ambiguous or incomplete
- The change touches multiple files or modules
- You're about to make an architectural decision
- The task would take more than 30 minutes to implement
- You have a **GitHub Project** for the work
- Stories and AC should be reviewable as issues on the board

**When NOT to use:** Single-line fixes, typo corrections, or changes where requirements are unambiguous and self-contained.

**Infra-only or tooling-only work** (no user-facing behavior): user stories may be omitted after the user confirms there is no end-user actor. Still write testable acceptance scenarios for the change itself.

## Load

1. [spec-story-ac-procedure.md](spec-story-ac-procedure.md) — story/AC subagents during Specify
2. [gh-spec-github-procedure.md](gh-spec-github-procedure.md) — Phase 0 branches and Phase 1.5 publish (**load at publish only**)
3. [SPEC.md.template](../../../../../docs/specs/SPEC.md.template) — skeleton when writing `docs/specs/<slug>/SPEC.md`

Collect inputs per [gh-spec.md](../../gh-spec.md) **Start** (home repo, GitHub Project, feature slug).

## Subagent orchestration (hub-and-spoke)

Story review, story drafting, and AC generation run in **readonly Task subagents**. The **parent** keeps clarifying questions, human approval gates, merge/dedupe, renumbering of `US-*` / `AC-*`, and writing `SPEC.md`.

Load [spec-story-ac-procedure.md](spec-story-ac-procedure.md) for when subagents are required, `subagent_type` selection, parallelism, [spec-story-ac-prompts.md](spec-story-ac-prompts.md) at dispatch, and merge/validate via `spec-story-ac-merge.py` before each human gate.

**Gates stay in the parent:** subagents never replace user approval of stories or AC.

## Phase 0 — Branch bootstrap + spec scaffold

After repo, project, and slug are known — **before** story review or SPEC writes:

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py init-spec-artifacts \
  --slug <feature-slug> \
  --title "<Feature Title>" \
  --repo-path "$(git rev-parse --show-toplevel)" \
  --repo "$(gh repo view --json nameWithOwner -q .nameWithOwner)" \
  --bootstrap
```

Or run branch bootstrap alone: [gh-spec-github-procedure](gh-spec-github-procedure.md) **Home repo (early, before SPEC.md writes)**.

Confirm `git branch --show-current` is `spec/<slug>`. All artifacts under `docs/specs/<slug>/` belong on this branch.

## Phase 1 — Specify (gated)

Do not write technical spec sections until stories and AC are approved. Do not publish until all gates pass.

### Clarifying questions

Ask until requirements are concrete:

1. Objective and target users
2. Core features and constraints
3. Tech stack preferences and constraints
4. Known boundaries (what to always do, ask first about, and never do)

**Surface assumptions immediately.** Before writing any spec content, list what you're assuming:

```
ASSUMPTIONS I'M MAKING:
1. This is a web application (not native mobile)
2. Authentication uses session-based cookies (not JWT)
3. The database is PostgreSQL (based on existing Prisma schema)
4. We're targeting modern browsers only (no IE11)
→ Correct me now or I'll proceed with these.
```

Don't silently fill in ambiguous requirements.

### Step 1 — User stories (required gate)

**Orchestration:** After the story-source question is answered, dispatch story subagents per [spec-story-ac-procedure](spec-story-ac-procedure.md). Merge subagent output, then present to the user.

**If the user provided zero user stories**, stop and ask:

> I don't have any user stories yet. Would you like to:
> 1. **Provide your own** — paste or describe one or more stories now, or
> 2. **Have me draft them** — I'll propose stories from what we've discussed so far?
>
> (For infra-only work with no end-user actor, say **skip stories** and I'll write acceptance scenarios for the technical change instead.)

**If the user provides one or more stories**, launch **story-review subagents** (one per story when parallel applies). Subagents check actor clarity, goal coherence, benefit linkage, scope (one testable slice), and flow across stories.

When a subagent recommends **revise** or **split**, present ORIGINAL vs PROPOSED side-by-side and **wait for approval** before Step 2.

**Story format:** flat `US-01`, `US-02`, … — `As a … I want … so that …`; no priority labels.

**GATE:** Every in-scope story is explicitly accepted by the user before Step 2.

### Step 2 — Acceptance criteria (required gate)

**Orchestration:** After the user accepts the story list, launch **AC subagents** per [spec-story-ac-procedure](spec-story-ac-procedure.md). Parent merges, assigns global `AC-*` IDs, dedupes cross-story overlap, then presents for user review.

Format and rules: [_docs/planning/ac-format-rules.md](../../../_docs/planning/ac-format-rules.md).

**GATE:** User has reviewed and accepted the acceptance scenarios. AC text goes in the **publish payload** and story sub-issues — not in `SPEC.md`.

### Step 3 — Technical spec sections

After stories and AC are approved, fill [SPEC.md.template](../../../../../docs/specs/SPEC.md.template) at `docs/specs/<slug>/SPEC.md`:

1. **Objective** — what and why; link `US-*` IDs; no duplicate AC text
2. **Commands** — full executable commands with flags
3. **Project Structure** — where source, tests, and docs live
4. **Code Style** — example snippet + conventions
5. **Testing Strategy** — framework, locations, coverage; map levels to `AC-*` where practical
6. **Boundaries** — Always / Ask first / Never
7. **Success criteria** — measurable outcomes not already captured as AC
8. **Open questions**

Update the **User story index** table: **Repositories** and **AC IDs** per story; **Issue** stays `TBD` until publish.

### Step 4 — Per-story repositories

For each `US-*`, list every `owner/repo` that needs implementation ([procedure: Per-story repositories](gh-spec-github-procedure.md)). Present the per-story table and `affected_repos` union for user approval with the full spec.

### Artifact layout

| Artifact | Location | Contents |
|----------|----------|----------|
| Technical spec | `docs/specs/<slug>/SPEC.md` | Objective, stack, commands, structure, code style, testing, boundaries, success criteria, open questions; **story index** (AC IDs + repos; issue links post-publish) |
| Per-story docs | `docs/user-stories/<branch-slug>.md` | Story narrative, AC summary, out-of-scope, dependencies — written per-story from [user-story.md.template](../../../../../docs/user-stories/user-story.md.template) by `finish-spec` |
| Manifest | `docs/specs/<slug>/gh-spec.manifest.json` | Written by `publish` — see [gh-spec.example.manifest.json](../../examples/gh-spec.example.manifest.json) |
| Stories + AC | GitHub sub-issues (layer 2) | Full `US-*` and `AC-*` Given/When/Then — **canonical for product sign-off** |
| Parent issue | GitHub (layer 1) | Links to `SPEC.md`; story index; status checklist |

**Post-publish formatting:** `finish-spec` runs `update-spec`, which writes `gh_spec` frontmatter and fills story index issue links from the manifest. Do not hand-author frontmatter or duplicate AC scenario text in `SPEC.md`.

For deeper edge-case review after AC approval, use [edge-cases](../lib/edge-cases.md) against the stories and AC before publish.

## Phase 1.5 — Publish to GitHub

**After** user approves the complete spec and repo mapping:

1. Build publish payload — [gh-spec.example.publish.json](../../examples/gh-spec.example.publish.json)
2. Pre-publish check:

```bash
python3 .cursor/commands/_scripts/gh/gh-spec-publish.py verify-spec \
  --spec-path docs/specs/<slug>/SPEC.md \
  --input publish-payload.json
```

3. Commit spec artifacts on `spec/<slug>`, push, then **`finish-spec`** — full sequence in [gh-spec-github-procedure](gh-spec-github-procedure.md) **Commands** and [Verification (parent, after publish)](gh-spec-github-procedure.md)

**Gate:** User sees parent + story issue links. **Stop** — `/gh-spec` is complete.

**Next (separate commands):** [/gh-plan](../../gh-plan.md) per story → [/gh-build](../../gh-build.md) per task.

## Keeping artifacts alive

- **AC changes:** edit the story sub-issue (canonical); update story index AC ID list in `SPEC.md` if IDs change
- **Technical spec changes:** edit `SPEC.md`; comment on parent issue when decisions are significant
- **Re-publish:** `publish` is idempotent — updates bodies, does not duplicate issues

## Pre-publish verification

- [ ] Story subagents ran (or inline exception per procedure)
- [ ] `spec-story-ac-merge.py validate-stories` passed on merged story output
- [ ] User stories approved (or user confirmed infra-only skip)
- [ ] AC subagents ran after story approval
- [ ] `spec-story-ac-merge.py validate-ac` passed; Given/When/Then AC approved by user
- [ ] Technical spec sections complete in `docs/specs/<slug>/SPEC.md`
- [ ] Story index lists every `US-*` with Repositories and AC IDs
- [ ] `verify-spec --input publish-payload.json` exits 0
- [ ] On `spec/<slug>`; home repo pushed before publish
- [ ] User approved spec + repo mapping
- [ ] `finish-spec` wrote `docs/user-stories/<branch-slug>.md` for each story (auto; check for skipped-file warnings)

Post-publish checks: [gh-spec-github-procedure](gh-spec-github-procedure.md) **Verification (parent, after publish)**.

## Red flags

- Starting to write code or create GitHub issues before spec approval
- Asking "should I just start building?" before clarifying what "done" means
- Generating acceptance criteria before user stories are approved
- Writing the technical spec before AC review is complete
- Doing story review or AC generation in the parent when [spec-story-ac-procedure](spec-story-ac-procedure.md) requires subagents
- Launching AC subagents before the user accepts the story list
- Duplicating AC scenarios in `SPEC.md` (index table only)
- Hand-authoring `gh_spec` frontmatter or issue links after publish
- Continuing to [/gh-plan](../../gh-plan.md), [/gh-build](../../gh-build.md), or [/plan](../lib/plan.md) / [/build](../lib/build.md) during `/gh-spec`
- Skipping `verify-spec` or post-publish verification

Publish-specific red flags: [gh-spec-github-procedure](gh-spec-github-procedure.md) **Red flags (orchestrator)**.

## Common rationalizations

| Rationalization | Reality |
|---|---|
| "This is simple, I don't need a spec" | Simple tasks still need acceptance scenarios. A two-line spec is fine. |
| "I'll write the spec after I code it" | That's documentation, not specification. |
| "User stories are overkill" | For user-facing work, stories + AC prevent building the wrong thing. Skip only when the user confirms infra-only scope. |
