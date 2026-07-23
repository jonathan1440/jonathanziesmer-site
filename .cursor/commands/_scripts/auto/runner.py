"""Shared spawn path for board dispatch and Phase 4 maintenance jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from log import RunLog, run_finished_record, run_started_record
from model_policy import resolve_model
from spawn_headless import spawn_headless
from spawn_worker import spawn_worker


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mark_attempt_started(job: dict[str, Any]) -> None:
    """Stamp per-attempt start time (distinct from job created_at)."""
    job["attempt_started_at"] = _now_iso()


def duration_seconds_for(job: dict[str, Any], *, ended: datetime | None = None) -> float | None:
    started_raw = job.get("attempt_started_at") or job.get("created_at")
    if not started_raw:
        return None
    try:
        started = datetime.fromisoformat(started_raw)
    except ValueError:
        return None
    ended = ended or datetime.now(timezone.utc)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return max(0.0, (ended - started).total_seconds())


def spawn_for_job(
    job: dict[str, Any],
    prompt: str,
    cfg: dict[str, Any],
    workspace: Path | str,
    log_dir: Path | str,
    *,
    spawn_headless_fn: Callable[..., dict[str, Any]] = spawn_headless,
    spawn_worker_fn: Callable[..., dict[str, Any]] = spawn_worker,
    run_log: RunLog | None = None,
) -> dict[str, Any]:
    """Launch a headless or worker backend for ``job`` and emit ``run_started``."""
    log_path = str(Path(log_dir) / "jobs" / f"{job['id']}.log")
    mode = cfg["spawn"]["mode"]
    model = resolve_model(cfg, job.get("prompt_class"), kind=job.get("kind"))
    job["mode"] = mode
    job["model"] = model
    job["log_path"] = log_path
    mark_attempt_started(job)

    if mode == "worker":
        worker = cfg["spawn"].get("worker") or {}
        result = spawn_worker_fn(
            prompt=prompt,
            model=model,
            worker_type=worker.get("type", "machine"),
            worker_name=worker.get("name"),
            repo_url=str(workspace),
            api_base=cfg["spawn"].get("api_base", "https://api.cursor.com"),
        )
    else:
        result = spawn_headless_fn(
            prompt=prompt,
            workspace=str(workspace),
            model=model,
            log_path=log_path,
        )

    job.update(result)
    job["status"] = "running"
    if run_log is not None:
        run_log.write(run_started_record(job, model=model))
    return job


def finish_and_log(
    job: dict[str, Any],
    *,
    registry,
    run_log: RunLog,
    status: str,
    exit_code: int | None = None,
    outcome_known: bool = True,
) -> dict[str, Any]:
    """Finalize a job in the registry and emit ``run_finished``."""
    duration = duration_seconds_for(job)
    finished = registry.finish_job(job, status=status, exit_code=exit_code)
    run_log.write(
        run_finished_record(
            finished,
            status=status,
            exit_code=exit_code,
            duration_seconds=duration,
            outcome_known=outcome_known,
        )
    )
    return finished
