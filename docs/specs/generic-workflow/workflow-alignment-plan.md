# Plan: Align pipeline commands with workflow-outline.md policy sections

**Source spec:** [workflow-outline.md](workflow-outline.md)
**Scope:** Close the eight gaps between the outline and the `.cursor/commands/gh/` pipeline. The machinery (commands, scripts, subagents, issue templates) already matches the outline's structure; what's missing is *policy* — merge strategy, severity gating, review cycles, post-merge/deployment — plus one template+script change (per-story docs) and three alignment decisions where the outline and the implementation deliberately diverge.

**Verified before planning:**

- `setup_pr_ruleset.py:132` already allows `["merge", "squash", "rebase"]` — gap 2 needs no ruleset change.
- Severity vocabularies in play today: outline uses **Blocker/Critical/Major/Minor**; `docs/templates/issues/bug.md:12` uses `MEDIUM`-style levels; `gh-review-review-synthesis.md:30` maps `CRITICAL/HIGH → Critical; MEDIUM → Important; LOW → Suggestion`; `gh-review-triage-rules.md:102` treats severity as optional metadata on CONFIRM/TRACK.
- `gh-spec-publish.py` renders `docs/specs/SPEC.md.template` via `render_spec_template()` (~line 2238) — the natural place to add user-story doc rendering.
- `gh-plan-procedure.md §Blocker rules` (line 148): independent-by-default, explicit direct-only blockers, max 3 external — the inverse of outline 2.a.vi.

---

## Decisions to lock first

These gate the work packages below. Each has a recommendation; record the final call in this file before starting.

### D1 — Severity scale (gates WP1)

**Recommendation: adopt the outline's `Blocker / Critical / Major / Minor`** as the single user-facing scale everywhere (bug template, triage rules, synthesis output). Rationale: the outline's merge-gate policy (§4.a.v, §7.b–d) is written in these terms, and it's the doc declared as source of truth. The synthesis procedure's internal `CRITICAL/HIGH/MEDIUM/LOW` reviewer-output levels can stay as raw input, but the mapping table changes to target the four-level scale (`CRITICAL → Blocker/Critical` per judgment, `HIGH → Critical/Major`, `MEDIUM → Major`, `LOW → Minor`).

### D2 — Default-blocking semantics (gap 8; gates WP6)

**Recommendation: keep the implementation's independent-by-default convention and amend the outline.** Outline 2.a.vi ("siblings block each other by default") would serialize task execution and defeat the parallel-planning/parallel-build design that the rest of the outline (2.a.v) explicitly optimizes for. The procedure's rules (explicit, direct-only, capped) are the deliberate, better-specified convention. Amend outline 2.a.vi to match; keep `gh-plan-procedure.md` untouched.

### D3 — Build escalation threshold (gap 7; gates WP5)

**Recommendation: keep gh-build's 3 verify-loop iterations and amend outline 3.a.vi / 7.a to say 3.** The two numbers measure slightly different things (verify iterations on the same failure class vs. "retry /gh-build attempts"), but two thresholds is one too many. Standardize on "3 iterations on the same failure class → comment on the task issue and stop," which is what `gh-build.md:37` already enforces mechanically.

### D4 — Where deployment risk tier lives (gap 6; gates WP4)

**Recommendation: declare the tier per-repo in `AGENTS.md`** (one line: `Release tier: low | medium | high`) rather than per-spec. The pipeline docs then reference it generically. This repo is a template; consumers set the tier once when they copy it.

---

## Work packages

Ordered per the suggested sequencing: review-policy cluster first (WP1–WP3), then the small doc addition (WP2 folds into it), the template+script work (WP3… see below), then alignment items.

### WP1 — Review policy: severity gating, cycle counts, manual-merge protocol (gaps 3, 4, 5)

One cluster; all lands in the gh-review/triage docs.

1. **New section `## Severity and merge gates` in `gh-review-triage-rules.md`** (after the CONFIRM/TRACK/DISMISS rules):
   - Severity becomes **required** on every CONFIRM (not optional metadata) — update line 102.
   - Gate rule per outline 4.a.v / §7.b–d: only **Blocker/Critical** findings block merge; **Major** becomes a follow-up bug issue (may still block story/spec PRs at reviewer discretion per 7.c); **Minor** is a follow-up, never blocks.
2. **Align severity vocabulary (per D1):**
   - `docs/templates/issues/bug.md` — change `**Severity:** MEDIUM` to the four-level scale with allowed values listed (`Blocker | Critical | Major | Minor`).
   - `gh-review-review-synthesis.md:30` — retarget the mapping to the four-level scale.
   - Grep the command tree for other `CRITICAL/HIGH/MEDIUM/LOW` severity references (reviewer subagent prompts in `.claude/agents/`) and note — reviewer raw output stays as-is; only synthesis/triage/template layers adopt the new scale.
3. **New section `## Review iteration cycles` in `gh-review.md`** (or `gh-review-procedure.md` if the command file must stay lean — prefer the command file since it's policy the orchestrator applies):
   - Task-level review: **1 cycle** of `/gh-review` + `/gh-resolve-issues`.
   - Story/spec-level review: **2 cycles** (cycle 2 catches regressions from cycle-1 fixes).
   - After the final cycle only Blocker/Critical blocks; new findings after the cycles route to `/gh-update-plan` or escalate — do **not** restart review (outline 4.c.iv).
4. **New section `## Manual review and merge` — add to `gh/README.md` §Flow** (it's a human protocol, not a command step), referenced from `gh-review.md` and `gh-resolve-issues.md` "Next step":
   - After `/gh-resolve-issues`, PR goes to human review.
   - Minor feedback (typos, small refactors, comments): manual fix + re-request.
   - Substantial feedback (new logic, architecture): new task/bug issue → `/gh-build` + `/gh-review` loop.
   - Max **2 re-request cycles**, then escalate to story/spec owner.
   - On approval, merge per the level's merge strategy (WP2).

**Acceptance:** grep for `Blocker` in triage rules and bug template hits the gate rule and scale; `gh-review.md` states cycle counts; README documents the manual protocol; no doc still presents severity as optional on CONFIRM.

### WP2 — Merge strategy by level (gap 2)

Docs-only (ruleset already permits all three methods).

1. **New section `## Merge strategy` in `gh/README.md`**, encoding outline §5:
   - Task PR (task → story): **squash** — clean story history, easy task revert.
   - Story PR (story → spec): **regular merge** — preserves task grouping.
   - Spec PR (spec → main): **squash** — minimal main history, easy spec rollback.
2. **Reference from `gh-build.md`** — one line in the checklist's finalize step (step 7) or Critical rules: "Task PRs squash-merge into the story branch — see [README §Merge strategy](README.md#merge-strategy)."
3. **Reference from the WP1 manual-merge section** ("merge per level — see §Merge strategy").
4. Optional: note in `scripts/github-setup/README.md` that the ruleset intentionally allows both squash and merge-commit to support the per-level strategy.

**Acceptance:** `grep -ri squash .cursor/commands/gh/README.md .cursor/commands/gh/gh-build.md` hits the strategy in both.

### WP3 — Per-story docs: template + /gh-spec wiring (gap 1)

The only item needing template + script changes.

1. **Create `docs/user-stories/user-story.md.template`** (location per outline 1.a.viii; sibling filled docs land in `docs/user-stories/<story-branch-slug>.md`). Fields mirror the user-story issue template (`docs/templates/issues/user-story.md`) plus doc-only sections: title, spec link (`docs/specs/<slug>/SPEC.md`), story issue placeholder, narrative ("As a / I want / So that"), acceptance criteria (`AC-*` IDs matching the spec's AC scheme), out-of-scope, dependencies. Use `{{PLACEHOLDER}}` tokens consistent with `SPEC.md.template`.
2. **Extend `gh-spec-publish.py`:**
   - Add `USER_STORY_TEMPLATE_PATH` alongside `SPEC_TEMPLATE_PATH` (~line 2205) and a `render_user_story_template(...)` mirroring `render_spec_template()`.
   - In the `finish-spec` path (which already creates story branches and issues from the manifest), render one doc per story into `docs/user-stories/`, filename derived from the existing story-branch slug helper (`slugify_story_title`, ~line 311). Skip-with-warning if the file exists (match SPEC.md `--force` semantics).
   - Commit the generated docs on the spec branch with the rest of the finish-spec output.
3. **Update `gh-spec-driven-development.md` (and `gh-spec.md` checklist if it enumerates artifacts):** add the step "fill out the per-story doc" during story definition / AC elaboration (outline 1.a.viii + 1.a.xi — ACs are recorded in the story docs, not just SPEC.md). The `spec-story-ac-procedure.md` flow should write ACs to both SPEC.md and the story doc — check `spec-story-ac-merge.py` to see whether it needs a second output target or the agent fills the story doc directly.
4. **Tests:** add coverage next to existing script tests (check `tests/` for `gh-spec-publish` tests) for template rendering + skip-if-exists.

**Acceptance:** running `/gh-spec` end-to-end produces `docs/user-stories/<slug>.md` per story with ACs filled; `pytest` passes; template exists and is the only unfilled copy.

### WP4 — Post-merge and deployment policy (gap 6)

1. **New section `## Post-merge and release` in `gh/README.md`** (end of §Flow), encoding outline §6:
   - Risk tiers: **low** (main always releasable, done = CI green), **medium** (manual staging validation before "shipped"), **high** (staged rollout before full release). Tier declared in `AGENTS.md` per D4.
   - **Spec issue closes only after deployment is confirmed** per the repo's tier — not at spec-PR merge.
   - **Link the release/deploy run to the spec issue** (comment with the release tag or Actions run URL) for the code→ship paper trail.
   - Reference [shipping-and-launch.md](procedures/lib/shipping-and-launch.md) for launch mechanics.
2. **Add one line to `AGENTS.md`** (this repo): `Release tier: medium` (staging validation exists in `deploy.yml`; prod is gated) — or whatever tier the team confirms.
3. **Wire the pipeline end state:** `gh-review.md` / `gh-resolve-issues.md` "Next step" sections currently dead-end at merge; add "spec-level: see README §Post-merge and release before closing the spec issue."

**Acceptance:** README documents tiers + close-on-deploy + release linkage; AGENTS.md declares the tier; at least one command doc points at the end state.

### WP5 — Escalation thresholds and /gh-update-plan triggers (gap 7)

1. **Per D3, amend the outline** (3.a.vi, 7.a): "after 2 attempts" → "after 3 verify iterations on the same failure class," matching `gh-build.md:37`. Add "escalate to the story owner" phrasing to gh-build's stop step so the outline's *who* is preserved: step 5 becomes "…comment a summary on the task issue, assign/mention the story owner, and stop (blocker)."
2. **Add a `## When to use — drift triggers` list to `gh-update-plan.md`** alongside the existing branch-drift gate, importing outline 2.b + 7.e verbatim:
   - Task estimated ≤2h reveals >4h of work.
   - Completed tasks reveal shared dependencies not visible at planning time.
   - Story acceptance criteria changed since planning.
   - Scope explosion: task >2× estimate or blocking multiple other tasks → escalate to story owner for the re-plan decision.
   - Anti-trigger: do **not** re-plan after every task; document the drift reason when invoking.
   - Note these are *reasons to invoke*; the mechanical branch-drift gate (`gh_scope_drift.py`) still governs what the command does once invoked.

**Acceptance:** outline and gh-build agree on one threshold; `gh-update-plan.md` lists all four triggers + the anti-trigger.

### WP6 — Default-blocking semantics (gap 8)

Per D2: **amend outline 2.a.vi** to match `gh-plan-procedure.md §Blocker rules` — tasks are independent by default; blocking relationships are explicit, direct-only (no transitive edges), max 3 external blockers per task with recorded reasons. Delete the "siblings block by default / track non-blocking explicitly" sentence. No procedure change.

### WP7 — Finalize

1. Regenerate the bridge after all `.cursor/` edits: `python3 .cursor/commands/_scripts/sync_claude_bridge.py`.
2. Validation: `ruff check app.py infrastructure scripts tests .github/scripts` (WP3 touches Python), `pytest`, and a grep sweep confirming no doc still uses the old severity scale in a policy position.
3. If the team wants this work tracked by its own pipeline: convert `workflow-outline.md` into a proper spec via `/gh-spec` (it currently sits outside the SPEC.md.template format) and turn WP1–WP6 into story/task issues. Otherwise execute directly on a branch.

---

## Sequencing summary

| Order | Package | Kind | Files touched |
|---|---|---|---|
| 0 | Decisions D1–D4 | decisions | this file |
| 1 | WP1 review policy (gaps 3–5) | docs | triage-rules, review-synthesis, bug template, gh-review.md, gh/README.md |
| 2 | WP2 merge strategy (gap 2) | docs | gh/README.md, gh-build.md |
| 3 | WP3 per-story docs (gap 1) | template + script + docs + tests | new template, gh-spec-publish.py, gh-spec-driven-development.md, tests |
| 4 | WP4 post-merge (gap 6) | docs | gh/README.md, AGENTS.md, gh-review/resolve next-steps |
| 5 | WP5 escalation (gap 7) | docs + outline | workflow-outline.md, gh-build.md, gh-update-plan.md |
| 6 | WP6 blocking default (gap 8) | outline only | workflow-outline.md |
| 7 | WP7 bridge + validation | tooling | `.claude/` bridge, test run |

WP1/WP2 and WP5/WP6 can run in parallel; WP3 is independent of all of them; WP7 is last.
