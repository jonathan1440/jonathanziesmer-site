# Phase 3 runbook — merge-triggered build chain + post-merge watch

**Parent:** [outline.md](./outline.md) · **Next:** [phase-4-runbook.md](./phase-4-runbook.md)
**Previous:** [phase-1-runbook.md](./phase-1-runbook.md) · [phase-2-runbook.md](./phase-2-runbook.md)

Phase 3 adds two polled signals on top of the Phase 1–2 status-transition poller
(`.cursor/commands/_scripts/auto/dispatch.py`):

1. **Task PR merged** → kick the next unblocked sibling Task under the same
   parent story (`chain.py`).
2. **Spec PR merged** → spawn a `post_merge` watch-and-report job, never a
   merge or a Spec close (`prompts.POST_MERGE_PROMPT`).

Both signals come from polling merged PRs (`prs.py`), not from a webhook or a
self-hosted runner — see [Decision: poller vs. runner](#decision-poller-vs-self-hosted-runner)
below.

---

## Prerequisites

- Phase 1–2 already running: `.cursor/auto-workflow.json` present and valid
  (`python3 .cursor/commands/_scripts/auto/dispatch.py once` exits 0 against a
  real project board).
- `gh` authenticated with `repo` and `project` scopes for `cfg.repo` and
  `cfg.project`.
- Task PR branches use `task/*`, Spec PR branches use `spec/*` (harness
  convention from `gh-build-publish.py`), and PR bodies contain `Closes
  owner/repo#N` (or GitHub's native "closing issue" linkage) so `prs.py` can
  resolve the issue a merged PR closes.
- `chain_failure_budget` and `merged_pr_lookback_hours` set in
  `.cursor/auto-workflow.json` (defaults: `3` and `72`).

---

## Merge → kick end-to-end

1. `dispatch_once` reaps finished jobs first. A reaped `build` job with
   `chain_kicked: true` and a terminal status of `failed`/`timeout`
   increments `chain_failures[parent_key]` via `chain.record_chain_failure`
   — once per failed *attempt*, independent of the job-level `retry_budget`
   retry/escalate decision that follows for that same job.
2. `prs.fetch_merged_prs(cfg["repo"], lookback_hours=...)` pages merged PRs,
   keeps only `task/*` and `spec/*` branches merged within the lookback
   window, and resolves each PR's closing issue(s) from
   `closingIssuesReferences` (falling back to parsing `Closes owner/repo#N`
   out of the PR body when GitHub's linkage is empty).
3. `prs.diff_merged_prs` drops PR keys already recorded in
   `state_dir/merged_prs.json`, so a PR is only processed once — except when
   a chain attempt is deferred by a lock (see below).
4. For each new `task_pr_merged` event, `chain.kick_next`:
   - Resolves the merged PR's Task issue and its parent story from the live
     Project items map (via `closing_issues`, `"owner/repo#N"` strings looked
     up directly in the items map).
   - Computes `parent_key = f"{repo}+parent#{parent_number}"` — the same
     format `filter.lock_key_for` uses for build locks, so a chain-kicked
     build and a normal Phase 1–2 build under the same story contend for one
     lock.
   - Lists sibling Tasks under that parent, filters to `status == todo`,
     `state == OPEN`, not escalated, no active job, and unblocked
     (`gh-build-publish.parse_blockers` + `check_blockers` on the
     `## Dependencies` section).
   - Picks the **lowest-numbered** eligible sibling, sets its Project status
     to `in_progress` (`set_project_status`, resolved from the issue URL —
     the board `project` passed in only carries `owner`/`number`), and
     returns a synthetic `build` transition for it.
5. The synthetic transition is merged with the normal status-transition list
   before `filter.filter_transitions` runs, so it's subject to the exact same
   concurrency/lock/escalation gates as any Phase 1–2 build.
6. On spawn, the job is tagged `chain_kicked: true` and `parent_key` so step 1
   can attribute a later failure back to the right story.
7. The status snapshot is updated so the kicked Task shows `in_progress`
   before it's saved, keeping the next poll's diff correct even if the
   Project API write in step 4 warns (no Status field, item not on board,
   etc.) instead of hard-failing.

### Locked retries

If `chain.kick_next` returns `{"action": "locked", ...}` (another build is
already running under the same parent), the merged PR's key is **not** added
to `merged_prs.json`. The next poll cycle re-evaluates the same merge event
once the lock frees, instead of silently dropping the chain.

### Budget exhaustion

If `chain_failures[parent_key] >= chain_failure_budget`, `kick_next` escalates
the parent story issue once (`escalate.escalate_issue`, latched via
`registry.mark_chain_escalated`) and returns `{"action": "budget_exhausted"}`.
The merge event is still marked handled — a human needs to intervene on the
story before the chain resumes; clear it with
`registry.clear_chain_failures(parent_key)` after triage.

---

## Post-merge end-to-end

1. A `spec_pr_merged` event resolves to the closing Spec issue via the same
   Project items map (`dispatch._resolve_spec_item`).
2. `filter.filter_post_merge_events` admits it as a `post_merge` actionable,
   respecting the concurrency slots already reserved by status-transition and
   chain-kick builds in the same cycle (`reserved=len(actionable)`).
3. The spawned agent follows `prompts.POST_MERGE_PROMPT`:
   - Watches the `deploy.yml` run on `main` via `gh run list` / `gh run watch`.
   - Comments on the Spec issue with the Actions run URL.
   - Runs `bash scripts/test-tier7-monitor.sh` against staging (exit code `2`
     is SKIP and acceptable; a real failure files a Bug issue and recommends a
     rollback).
   - **Never** closes the Spec issue and **never** merges anything — this
     repo's medium release tier requires human QA or manual sign-off on
     staging before a Spec issue can be closed (see `AGENTS.md` § Release
     tier).

---

## Failure budget summary

| Registry field | Meaning | Cleared by |
|---|---|---|
| `chain_failures[parent_key]` | Consecutive chain-kicked build failures under a story | `chain.clear_chain_failures` (manual, after triage) |
| `chain_escalated` | Latch preventing repeat escalation comments for the same story | Not auto-cleared; remove manually once the budget resets |
| `escalated_issues` | Phase 1–2 latch for a single issue's escalation | Cleared automatically on the next status transition for that issue |

---

## Decision: poller vs. self-hosted runner

**Decided (see [outline.md](./outline.md) open item O.6):** the existing
polling dispatcher (`dispatch.py poll`) is sufficient for Phase 3. A
self-hosted GitHub Actions runner (native `pull_request` / `check_suite`
event delivery, no polling latency) is deferred — it adds a CI trust-boundary
surface and an always-on host requirement that isn't justified while
`poll_interval_seconds` (default `60`) is fast enough for the build-chain and
post-merge use cases here.

---

## Related files

| Path | Role |
|---|---|
| `.cursor/commands/_scripts/auto/prs.py` | Merged-PR polling, branch classification, closing-issue resolution |
| `.cursor/commands/_scripts/auto/chain.py` | Next-unblocked-Task selection, lock/budget gates |
| `.cursor/commands/_scripts/auto/dispatch.py` | Wires reap → fetch → chain kick → post-merge → filter → spawn |
| `.cursor/commands/_scripts/auto/prompts.py` | `POST_MERGE_PROMPT` and `build_prompt` dispatch |
| `tests/auto/test_prs.py`, `test_chain.py` | Phase 3 unit coverage |
| `tests/auto/test_dispatch.py` | Merge → kick → spawn and locked-retry integration coverage |
