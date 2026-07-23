# launchd — auto-workflow poller, worker, maintenance, summary

Optional `launchd` agents for an always-on Mac (see
[outline.md](../../../../../docs/specs/auto-workflow/outline.md) practical
constraints). Templates:

| Label | Role | Schedule |
| --- | --- | --- |
| `com.sample-aws.auto-workflow.poller` | `dispatch.py once` | every 60s |
| `com.sample-aws.auto-workflow.worker` | `agent worker start` (iOS inbox / Remote Control) | KeepAlive |
| `com.sample-aws.auto-workflow.maintenance` | `maintenance.py run-all` | daily 07:15 local |
| `com.sample-aws.auto-workflow.summary` | `usage_summary.py` (previous UTC day) | daily 06:05 local |

Per-job cadences (weekly deps, monthly ruff, …) are enforced inside
`maintenance.py` via `maintenance.jobs.*.interval_hours` — the daily timer
only invokes jobs that are due.

## Install

```bash
# from repo root
bash .cursor/commands/_scripts/auto/launchd/install.sh poller        # or worker | maintenance | summary | both | all
```

`install.sh` renders `__REPO_ROOT__` into `~/Library/LaunchAgents/` and loads
the agent(s).

Before loading the poller, confirm config:

```bash
python3 .cursor/commands/_scripts/auto/dispatch.py once --repo-root "$(pwd)"
```

Host-specific values (project number, worker name, AWS profile, escalate
owner) belong in gitignored `.cursor/auto-workflow.local.json` — deep-merged
over `.cursor/auto-workflow.json`.

## Manual dry runs

```bash
python3 .cursor/commands/_scripts/auto/maintenance.py due --repo-root "$(pwd)"
python3 .cursor/commands/_scripts/auto/maintenance.py run deps_bump --repo-root "$(pwd)" --force
python3 .cursor/commands/_scripts/auto/usage_summary.py --repo-root "$(pwd)" --date 2026-07-16
```

## AWS SSO (tier7_staging)

The profile is derived from `cdk.json` — `maintenance.aws_environment`
(default `staging`) picks a `context.<env>` block and the profile name follows
`gen_aws_profiles.py`: `{repo-dir-slug}_{env}` (e.g.
`sample_aws_project_staging`). Set `maintenance.aws_profile` explicitly only to
override. `cdk.json` must define the chosen environment (staging + production
ship by default); an unknown `aws_environment` fails config validation.

Generate the profiles (needs `account` in each `cdk.json` env block) and log in:

```bash
python3 .cursor/commands/_scripts/aws/gen_aws_profiles.py "$(git rev-parse --show-toplevel)"
aws sso login --sso-session plnu   # or your session name
```

If SSO is expired or `scripts/test-tier7-local.sh` is missing (exit 2 SKIP),
the job files/updates **one** deduplicated Task setup alert — not an
infrastructure Bug. Expired auth never invents credentials.

## Logs

```bash
launchctl list | grep auto-workflow
tail -f .cursor/auto-workflow/logs/launchd-maintenance.out.log
tail -f .cursor/auto-workflow/logs/launchd-summary.out.log
ls .cursor/auto-workflow/logs/summaries/
```

## Uninstall

```bash
for label in poller worker maintenance summary; do
  launchctl bootout "gui/$(id -u)/com.sample-aws.auto-workflow.${label}" 2>/dev/null || true
done
rm -f ~/Library/LaunchAgents/com.sample-aws.auto-workflow.*.plist
```

## Recovery

| Symptom | Fix |
| --- | --- |
| Maintenance claim stuck (`skipped_busy`) | Delete `state/memory/<job>/*.claim` older than `claim_ttl_seconds`, or wait for TTL |
| Duplicate PR risk after state wipe | Probes also query open PRs for marker strings before spawn |
| Summary empty | Confirm NDJSON under `log_dir/YYYY-MM-DD.ndjson`; summary defaults to **yesterday UTC** |
| Worker jobs always timeout | Expected today — outcomes marked `outcome_known=false`; not counted as known failures |

## Notes

- `dispatch.py poll` sleeps `poll_interval_seconds` between cycles when run
  manually; the poller plist uses `once` + `StartInterval` 60.
- If `spawn.mode` is `"worker"`, ensure the worker agent is loaded and
  `CURSOR_API_KEY` / auth token is available to the `launchd` environment.
- Usage summaries never post GitHub issues. Admin API enrichment is optional
  and not wired.
