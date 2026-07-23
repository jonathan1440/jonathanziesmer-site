# Phase 4 runbook — background maintenance + usage visibility

**Parent:** [outline.md](./outline.md) · **Previous:** [phase-3-runbook.md](./phase-3-runbook.md)

Phase 4 adds scheduled hybrid maintenance jobs and a nightly local usage
summary on top of the Phase 1–3 dispatcher.

## Architecture

```text
launchd (daily) → maintenance.py run-all
                     │
                     ├─ due? (interval_hours + last_run)
                     ├─ deterministic probe (maintenance_checks.py)
                     ├─ fingerprint + MemoryStore claim
                     ├─ noop / known_good / busy → done
                     └─ spawn / setup_alert → runner.py → headless agent

launchd (nightly) → usage_summary.py
                     └─ log_dir/*.ndjson → log_dir/summaries/YYYY-MM-DD.json
```

Deterministic probes decide whether work is needed. Judgment-heavy PR/issue
work runs as a local Cursor agent. Never auto-merge.

## Jobs (4.1)

| Job | Default interval | Probe | Agent action |
| --- | --- | --- | --- |
| `deps_bump` | 168h (weekly) | Compare requirement floors + CDK CLI pin to latest | One PR raising floors / CDK pin; tiers 1–4 |
| `ruff_rules` | 720h (monthly) | Candidate rule families not yet selected | One narrow adoption PR; tiers 1–4 |
| `docs_drift` | 168h | Hash of `AGENTS.md` + `CLAUDE.md` vs checkpoint | File/update Task only — never rewrite contract |
| `stale_triage` | 168h / 30 days | Board issues older than `stale_days` | Deduped comments; never close or move cards |
| `tier7_staging` | 24h | SSO preflight + `scripts/test-tier7-monitor.sh` | Setup Task (exit 2 / expired SSO) or Bug (anomaly) |

Markers for GitHub-side dedupe live in `maintenance_checks.py`
(`auto-workflow:maintenance:*`).

### Tier-7 host limits

This phase does **not** add `scripts/test-tier7-local.sh`, AWS account IDs, or
credentials. Missing checks (exit 2) or expired SSO become one deduplicated
setup alert. Real check failures file/update one Bug per anomaly fingerprint.

The AWS profile is **derived from `cdk.json`**: `maintenance.aws_environment`
(default `staging`) selects a `context.<env>` block, and the profile name is
`{repo-dir-slug}_{env}` — matching `gen_aws_profiles.py`. `cdk.json` ships
`staging` + `production`, so `sample_aws_project_staging` and
`sample_aws_project_production` are both derivable. `load_config` records the
discovered environments/profiles under `maintenance.cdk_environments` /
`maintenance.cdk_profiles`. Set `maintenance.aws_profile` only to override; an
`aws_environment` absent from `cdk.json` fails validation. Actual `~/.aws`
profiles still require `account` IDs in each env block + `gen_aws_profiles.py`.

## Memory (4.2)

`MemoryStore` under `state_dir/memory/<job>/`:

- `<fingerprint>.claim` — exclusive lease (`O_CREAT|O_EXCL`), TTL from
  `maintenance.claim_ttl_seconds`
- `<fingerprint>.json` — known-good receipt (deterministic noops only)
- `last_run.json` — due scheduling checkpoint
- `docs_drift/checkpoint.json` — last known-good contract hash

Spawned agent success **releases** the claim without a receipt so a no-PR
exit does not permanently suppress the job. Re-fire is gated by intervals +
open-PR / marker checks.

## Usage summary (4.3)

Lifecycle events (schema version 1):

- `run_started` / `run_finished` with `run_id` (`<job_id>:<attempt>`), kind,
  prompt class, mode, model, request_id, status, exit_code, duration_seconds,
  `outcome_known`

Worker timeouts are `outcome_known=false` (not invented failures).

```bash
python3 .cursor/commands/_scripts/auto/usage_summary.py --repo-root "$(pwd)"
# default date = yesterday UTC
```

Writes `log_dir/summaries/YYYY-MM-DD.json`. No GitHub issues. Admin API
enrichment is optional and not a dependency.

## Config

Base: [`.cursor/auto-workflow.json`](../../../.cursor/auto-workflow.json)  
Host overrides (gitignored): `.cursor/auto-workflow.local.json` (deep-merged)

```json
{
  "project": {"number": 123},
  "maintenance": {
    "aws_environment": "staging",
    "stale_days": 30,
    "jobs": {"deps_bump": {"interval_hours": 24}}
  }
}
```

`aws_profile` is derived from `cdk.json` + `aws_environment`; set it explicitly
only to override the derived name.

## CLI

```bash
python3 .cursor/commands/_scripts/auto/maintenance.py due
python3 .cursor/commands/_scripts/auto/maintenance.py run <job> [--force]
python3 .cursor/commands/_scripts/auto/maintenance.py run-all [--force]
python3 .cursor/commands/_scripts/auto/usage_summary.py [--date YYYY-MM-DD]
```

## launchd

See [launchd/README.md](../../../.cursor/commands/_scripts/auto/launchd/README.md).

```bash
bash .cursor/commands/_scripts/auto/launchd/install.sh maintenance
bash .cursor/commands/_scripts/auto/launchd/install.sh summary
# or: install.sh all
```

## Related files

| Path | Role |
| --- | --- |
| `.cursor/commands/_scripts/auto/maintenance.py` | Due / run / run-all CLI |
| `.cursor/commands/_scripts/auto/maintenance_checks.py` | Deterministic probes |
| `.cursor/commands/_scripts/auto/memory.py` | Fingerprint claims + receipts |
| `.cursor/commands/_scripts/auto/usage_summary.py` | Nightly aggregation |
| `.cursor/commands/_scripts/auto/runner.py` | Shared spawn + lifecycle emit |
| `.cursor/commands/_scripts/auto/log.py` | Schema-versioned NDJSON |
| `tests/auto/test_maintenance*.py`, `test_memory.py`, `test_usage_summary.py`, `test_log.py` | Coverage |
