# Phase 2 runbook — local operation (CLI + spawn backends)

**Parent:** [outline.md](./outline.md) · **Previous:** [phase-1-runbook.md](./phase-1-runbook.md) · **Next:** [phase-3-runbook.md](./phase-3-runbook.md) · [phase-4-runbook.md](./phase-4-runbook.md)

Phase 2 turns the Phase 1 classification logic into something that actually
runs: a CLI entry point, two spawn backends, and a per-day NDJSON log.

## Entry point

```bash
python3 .cursor/commands/_scripts/auto/dispatch.py once   # single poll cycle, exits
python3 .cursor/commands/_scripts/auto/dispatch.py poll    # loop forever, sleeping cfg.poll_interval_seconds
```

Both read `.cursor/auto-workflow.json` (never `cdk.json`) via
`config.load_config`. `--repo-root <path>` overrides the repo root used to
resolve the config file and its relative paths.

## Spawn backends

Selected via `cfg["spawn"]["mode"]`:

- **`headless`** — `spawn_headless.spawn_headless(*, prompt, workspace, model=None, log_path=None, env=None)`
  launches a detached `cursor-agent -p -f --approve-mcps` subprocess and
  returns immediately with its pid.
- **`worker`** — `spawn_worker.spawn_worker(*, prompt, model, worker_type, worker_name, repo_url, api_base)`
  calls the Cursor Cloud Agent API (`CURSOR_API_KEY` required) and returns a
  `chat_id`/`request_id`; there is no local pid to track, so
  `Registry.reap()` uses a stale timeout (`STALE_TIMEOUT_SECONDS`, 6h)
  instead of a liveness check.

## Running locally

`docs/specs/auto-workflow/outline.md` §"Practical constraints" covers keeping
a host online for polling (a Mac mini with `launchd`, or a server with
`cron`/`systemd`). A minimal `launchd` plist template lives under
`.cursor/commands/_scripts/auto/launchd/` — see that directory's `README.md`
for install steps.

## Logging

`log.RunLog(log_dir)` appends one JSON line per event to
`log_dir/<YYYY-MM-DD>.ndjson` — `reap`, `reap_failed`, `retry_spawn`,
`escalated`, `merge_seen`, `chain_kick`, `chain_locked`, `spawn`, and
`spawn_error`. Rotate/prune these files outside the harness (they are not
auto-pruned).

## Validate before enabling `poll`

```bash
python3 .cursor/commands/_scripts/auto/dispatch.py once
```

should exit 0 against the real Project board and repo in
`.cursor/auto-workflow.json`, with `gh` authenticated for both.

## Related files

| Path | Role |
|---|---|
| [phase-1-runbook.md](./phase-1-runbook.md) | Fetch/diff/classify/lock logic this phase runs |
| [phase-3-runbook.md](./phase-3-runbook.md) | Adds merge-triggered build chain + post-merge watch on top |
| `tests/auto/test_spawn.py`, `test_dispatch.py` | Phase 2 unit/integration coverage |
