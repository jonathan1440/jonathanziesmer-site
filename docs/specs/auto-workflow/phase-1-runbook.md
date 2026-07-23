# Phase 1 runbook — status-transition polling

**Parent:** [outline.md](./outline.md) · **Next:** [phase-2-runbook.md](./phase-2-runbook.md)

Phase 1 is the foundation of the auto-workflow poller
(`.cursor/commands/_scripts/auto/dispatch.py`): fetch the GitHub Project v2
board, diff it against the last saved snapshot, and turn each status change
into a job the dispatcher can spawn a Cursor agent for.

## Modules

| Module | Role |
|---|---|
| `config.py` | Loads and validates `.cursor/auto-workflow.json`; resolves `workspace`/`state_dir`/`log_dir` to absolute paths |
| `fetch.py` | `fetch_project_items(owner, number)` — pages the Project v2 GraphQL API, normalizes each item |
| `diff.py` | Normalizes raw Status/issue-type strings; `snapshot_from_items` + `diff_snapshots` compute transitions between polls |
| `filter.py` | `classify_transition` maps a transition to a dispatch kind (`build`, `review_resolve`, `plan`, `review_resolve_2cycle`); `filter_transitions` gates by concurrency, per-story build locks, and escalation |
| `registry.py` | `Registry(state_dir)` — file-backed job/lock/snapshot/escalation state under `state_dir` |
| `prompts.py` | Prompt templates per dispatch kind |
| `spawn_headless.py` / `spawn_worker.py` | Launch a `cursor-agent` CLI subprocess or a Cursor Cloud Agent run |
| `escalate.py` | Comments on an issue (`"owner/repo#N"`) when a job needs human attention |
| `log.py` | `RunLog(log_dir)` — append-only NDJSON event log |

## Status transitions handled

- Task `todo -> in_progress` (not a cold/new appearance) → `build`
- Task `-> review_qa` → `review_resolve`
- User Story `todo -> in_progress` with zero Task sub-issues → `plan`
- User Story / Spec `-> review_qa` → `review_resolve_2cycle`

A brand-new item on the board (`from_status is None`) is never actionable —
only real transitions between polls are.

## Locking and concurrency

`build` jobs lock on the parent story via `filter.lock_key_for`
(`f"{repo}+parent#{parent_number}"`, or `f"{repo}+{issue}"` when there is no
parent); every other kind locks on the issue itself. `filter_transitions`
admits transitions up to `cfg["concurrency"]`, skipping issues that are
escalated, already have an active job, or whose build lock is already held.

## Retry and escalation

Each spawned job starts at `attempts=1`. On the next poll, `Registry.reap()`
finalizes jobs whose process has died (headless) or that exceeded the stale
timeout (worker). A failed/timed-out job with `attempts <= retry_budget` is
retried in the same cycle (`Registry.bump_attempt`); otherwise the issue is
marked escalated and `escalate.escalate_issue` posts a comment.

## Related files

| Path | Role |
|---|---|
| [phase-2-runbook.md](./phase-2-runbook.md) | Local operation (CLI, poll loop) |
| [phase-3-runbook.md](./phase-3-runbook.md) | Merge-triggered build chain + post-merge watch |
| [phase-4-runbook.md](./phase-4-runbook.md) | Maintenance timers, memory, usage summary |
| `tests/auto/test_config.py`, `test_fetch.py`, `test_diff.py`, `test_filter.py`, `test_registry.py` | Phase 1 unit coverage |
