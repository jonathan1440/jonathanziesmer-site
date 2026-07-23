"""Phase 4 maintenance CLI.

Usage:
  python3 maintenance.py due [--repo-root PATH]
  python3 maintenance.py run <job> [--repo-root PATH] [--force]
  python3 maintenance.py run-all [--repo-root PATH] [--force]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import maintenance_checks as checks
from admission import admit_and_spawn
from config import MAINTENANCE_JOB_NAMES, load_config, resolve_path
from intent_queue import IntentQueue
from log import RunLog
from memory import MemoryStore, fingerprint
from registry import Registry
from spawn_headless import spawn_headless
from spawn_worker import spawn_worker

def _repo_root_from_script() -> Path:
    return _SCRIPT_DIR.parents[3]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def job_is_due(
    job_name: str,
    cfg: dict[str, Any],
    memory: MemoryStore,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> bool:
    maintenance = cfg.get("maintenance") or {}
    if not maintenance.get("enabled", True):
        return False
    jobs = maintenance.get("jobs") or {}
    job_cfg = jobs.get(job_name) or {}
    if not job_cfg.get("enabled", True):
        return False
    if force:
        return True
    interval_hours = float(job_cfg.get("interval_hours") or 24)
    last = memory.last_run(job_name)
    if last is None:
        return True
    now = now or _now()
    elapsed = (now - last).total_seconds() / 3600.0
    return elapsed >= interval_hours


def list_due_jobs(
    cfg: dict[str, Any],
    memory: MemoryStore,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> list[str]:
    return [
        name
        for name in sorted(MAINTENANCE_JOB_NAMES)
        if job_is_due(name, cfg, memory, now=now, force=force)
    ]


def _policy_version(cfg: dict[str, Any], job_name: str) -> int | str:
    jobs = (cfg.get("maintenance") or {}).get("jobs") or {}
    return (jobs.get(job_name) or {}).get("policy_version", 1)


def _load_checkpoint(memory: MemoryStore) -> str | None:
    path = memory.task_dir("docs_drift") / "checkpoint.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return data.get("agents_hash")


def _save_checkpoint(memory: MemoryStore, agents_hash: str) -> None:
    path = memory.task_dir("docs_drift") / "checkpoint.json"
    path.write_text(
        json.dumps(
            {"agents_hash": agents_hash, "saved_at": _now().isoformat()},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def run_probe(
    job_name: str,
    cfg: dict[str, Any],
    *,
    memory: MemoryStore,
    registry: Registry,
    probe_overrides: dict[str, Callable[..., dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Execute the deterministic probe for ``job_name``."""
    root = Path(cfg["_repo_root"])
    repo = cfg["repo"]
    maintenance = cfg.get("maintenance") or {}
    overrides = probe_overrides or {}

    if job_name in overrides:
        return overrides[job_name]()

    if job_name == "deps_bump":
        return checks.probe_deps_bump(repo_root=root, repo=repo)
    if job_name == "ruff_rules":
        return checks.probe_ruff_rules(repo_root=root, repo=repo)
    if job_name == "docs_drift":
        return checks.probe_docs_drift(
            repo_root=root,
            repo=repo,
            checkpoint_hash=_load_checkpoint(memory),
        )
    if job_name == "stale_triage":
        from fetch import _load_gh_spec_publish

        module = _load_gh_spec_publish()
        active = {
            job["issue"]
            for job in registry._data.get("jobs", {}).values()
            if job.get("status") in ("pending", "running") and job.get("issue")
        }
        return checks.probe_stale_triage(
            owner=cfg["project"]["owner"],
            project_number=int(cfg["project"]["number"]),
            stale_days=int(maintenance.get("stale_days") or 30),
            graphql_fn=module.graphql_with_features,
            active_issues=active,
        )
    if job_name == "tier7_staging":
        return checks.probe_tier7_staging(
            repo_root=root,
            aws_profile=str(maintenance.get("aws_profile") or "sample_aws_project_staging"),
        )
    raise ValueError(f"unknown maintenance job: {job_name!r}")


def _prompt_class_for(job_name: str, probe: dict[str, Any]) -> str:
    if job_name == "tier7_staging":
        if probe.get("action") == "setup_alert":
            return "maintenance_tier7_setup"
        return "maintenance_tier7_anomaly"
    return f"maintenance_{job_name}"


def _transition_for(job_name: str, cfg: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
    ctx = probe.get("context") or {}
    return {
        "repo": cfg["repo"],
        "bumps_json": json.dumps(ctx.get("bumps") or {}, sort_keys=True),
        "opportunities_json": json.dumps(ctx.get("opportunities") or [], sort_keys=True),
        "candidates_json": json.dumps(ctx.get("candidates") or [], sort_keys=True),
        "details_json": json.dumps(
            {k: ctx.get(k) for k in ("auth", "stdout", "stderr", "exit_code") if k in ctx},
            sort_keys=True,
            default=str,
        ),
        "marker": ctx.get("marker", ""),
        "agents_hash": ctx.get("agents_hash", ""),
        "checkpoint_hash": ctx.get("checkpoint_hash", ""),
        "stale_days": ctx.get("stale_days", (cfg.get("maintenance") or {}).get("stale_days", 30)),
        "escalate_owner": cfg.get("escalate_owner") or "",
        "reason": probe.get("reason", ""),
        "profile": ctx.get("profile") or (cfg.get("maintenance") or {}).get("aws_profile", ""),
        "exit_code": ctx.get("exit_code", ""),
        "issue": f"maintenance:{job_name}",
        "url": "",
        "title": f"maintenance {job_name}",
    }


def run_job(
    job_name: str,
    cfg: dict[str, Any],
    *,
    force: bool = False,
    now: datetime | None = None,
    spawn_headless_fn=spawn_headless,
    spawn_worker_fn=spawn_worker,
    probe_overrides: dict[str, Callable[..., dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Probe + claim + noop/spawn one maintenance job."""
    if job_name not in MAINTENANCE_JOB_NAMES:
        raise ValueError(f"unknown maintenance job: {job_name!r}")

    root = Path(cfg["_repo_root"])
    state_dir = resolve_path(root, cfg["state_dir"])
    log_dir = resolve_path(root, cfg["log_dir"])
    workspace = resolve_path(root, cfg.get("workspace") or ".")
    memory = MemoryStore(state_dir)
    registry = Registry(state_dir)
    run_log = RunLog(log_dir)
    now = now or _now()

    if not job_is_due(job_name, cfg, memory, now=now, force=force):
        return {"job": job_name, "status": "skipped_not_due"}

    probe = run_probe(
        job_name, cfg, memory=memory, registry=registry, probe_overrides=probe_overrides
    )
    memory.mark_last_run(job_name, now)

    # First-time docs checkpoint: record hash, no spawn.
    if job_name == "docs_drift" and (probe.get("context") or {}).get("establish_checkpoint"):
        _save_checkpoint(memory, probe["context"]["agents_hash"])
        memory.complete(
            job_name,
            fingerprint(job_name, probe["inputs"], _policy_version(cfg, job_name)),
            metadata={"reason": probe["reason"]},
        )
        return {"job": job_name, "status": "checkpoint_established", "probe": probe}

    fp = fingerprint(job_name, probe["inputs"], _policy_version(cfg, job_name))
    ttl = int((cfg.get("maintenance") or {}).get("claim_ttl_seconds") or 21600)
    claim = memory.claim(job_name, fp, ttl_seconds=ttl, now=now)

    if claim == "known_good":
        return {"job": job_name, "status": "skipped_known_good", "fingerprint": fp, "probe": probe}
    if claim == "busy":
        return {"job": job_name, "status": "skipped_busy", "fingerprint": fp, "probe": probe}

    action = probe.get("action")
    if action == "noop" or probe.get("duplicate"):
        memory.complete(job_name, fp, metadata={"reason": probe.get("reason"), "action": action})
        # Docs drift noop after spawn success should refresh checkpoint when hashes match
        if job_name == "docs_drift" and probe["inputs"].get("agents_hash"):
            # only when already matching checkpoint
            if probe["inputs"].get("checkpoint_hash") == probe["inputs"].get("agents_hash"):
                _save_checkpoint(memory, probe["inputs"]["agents_hash"])
        return {
            "job": job_name,
            "status": "noop",
            "fingerprint": fp,
            "probe": probe,
        }

    # setup_alert and spawn both need an agent (judgment + GitHub write).
    prompt_class = _prompt_class_for(job_name, probe)
    transition = _transition_for(job_name, cfg, probe)
    transition["issue"] = f"maintenance:{job_name}:{fp[:12]}"
    intent_queue = IntentQueue(state_dir)
    result = admit_and_spawn(
        cfg=cfg,
        registry=registry,
        run_log=run_log,
        workspace=workspace,
        log_dir=log_dir,
        kind=f"maintenance_{job_name}",
        prompt_class=prompt_class,
        transition=transition,
        lock_key=f"maintenance:{job_name}",
        intent_queue=intent_queue,
        job_extras={
            "fingerprint": fp,
            "maintenance_task": job_name,
            "target": job_name,
            "repo": cfg["repo"],
        },
        spawn_headless_fn=spawn_headless_fn,
        spawn_worker_fn=spawn_worker_fn,
    )
    if result["status"] == "spawned":
        job = result["job"]
        run_log.write(
            {
                "event": "maintenance_spawn",
                "job_id": job["id"],
                "maintenance_task": job_name,
                "fingerprint": fp,
                "action": action,
                "reason": probe.get("reason"),
            }
        )
        return {
            "job": job_name,
            "status": "spawned",
            "fingerprint": fp,
            "job_record": job,
            "probe": probe,
        }
    if result["status"] == "queued":
        return {
            "job": job_name,
            "status": "queued",
            "fingerprint": fp,
            "intent": result.get("intent"),
            "probe": probe,
        }
    if result["status"] == "spawn_error":
        memory.fail(job_name, fp, error=result.get("reason") or "spawn_error")
        return {
            "job": job_name,
            "status": "spawn_error",
            "fingerprint": fp,
            "error": result.get("reason"),
            "probe": probe,
        }
    memory.release_claim(job_name, fp)
    return {
        "job": job_name,
        "status": "skipped",
        "reason": result.get("reason"),
        "fingerprint": fp,
        "probe": probe,
    }


def run_all(
    cfg: dict[str, Any],
    *,
    force: bool = False,
    **kwargs,
) -> list[dict[str, Any]]:
    state_dir = resolve_path(Path(cfg["_repo_root"]), cfg["state_dir"])
    memory = MemoryStore(state_dir)
    due = list_due_jobs(cfg, memory, force=force)
    return [run_job(name, cfg, force=force, **kwargs) for name in due]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["due", "run", "run-all"])
    parser.add_argument("job", nargs="?", help="Job name for `run`")
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else _repo_root_from_script()
    cfg = load_config(repo_root)
    memory = MemoryStore(resolve_path(repo_root, cfg["state_dir"]))

    if args.command == "due":
        due = list_due_jobs(cfg, memory, force=args.force)
        print(json.dumps({"due": due}, indent=2))
        return 0

    if args.command == "run":
        if not args.job:
            parser.error("run requires a job name")
        result = run_job(args.job, cfg, force=args.force)
        print(json.dumps({k: v for k, v in result.items() if k != "job_record"}, indent=2, default=str))
        return 0 if result.get("status") != "spawn_error" else 1

    results = run_all(cfg, force=args.force)
    print(
        json.dumps(
            [{k: v for k, v in r.items() if k != "job_record"} for r in results],
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
