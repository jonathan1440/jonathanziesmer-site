"""File-backed job registry: registry.json + jobs/*.json + snapshot.json + merged_prs.json.

Construct with a `state_dir` path (not the whole config):

    registry = Registry(state_dir)

Writes use an exclusive ``fcntl`` lock + atomic replace so concurrent poller,
maintenance, and orchestrator processes do not clobber each other.
"""

from __future__ import annotations

import fcntl
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import ensure_dir

STALE_TIMEOUT_SECONDS = 6 * 3600


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _infer_log_status(log_path: str | None) -> str:
    if not log_path:
        return "completed"
    path = Path(log_path)
    if not path.is_file():
        return "completed"
    last_line = ""
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if line:
            last_line = line
    if not last_line:
        return "completed"
    try:
        record = json.loads(last_line)
    except json.JSONDecodeError:
        return "completed"
    status = str(record.get("status", "")).lower()
    if status in ("failure", "failed", "error"):
        return "failed"
    if status in ("success", "completed", "ok"):
        return "completed"
    return "completed"


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON via temp file + replace while holding an exclusive flock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(lock_path, "a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")
            tmp_path.replace(path)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class Registry:
    """Loads/saves `registry.json` (and `jobs/`, `snapshot.json`, `merged_prs.json`)
    under `state_dir`."""

    def __init__(self, state_dir: Path | str) -> None:
        self.state_dir = ensure_dir(state_dir)
        self.jobs_dir = ensure_dir(self.state_dir / "jobs")
        self.registry_path = self.state_dir / "registry.json"
        self.snapshot_path = self.state_dir / "snapshot.json"
        self.merged_prs_path = self.state_dir / "merged_prs.json"
        self._data = self._load_registry()

    # -- registry.json -----------------------------------------------------

    def _load_registry(self) -> dict[str, Any]:
        if self.registry_path.is_file():
            try:
                data = json.loads(self.registry_path.read_text())
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}
        data.setdefault("jobs", {})
        data.setdefault("escalated_issues", [])
        data.setdefault("chain_failures", {})
        data.setdefault("chain_escalated", [])
        data.setdefault("risk_latched_issues", [])
        return data

    def _reload(self) -> None:
        """Refresh in-memory view from disk (call under lock before mutate)."""
        self._data = self._load_registry()

    def _save(self) -> None:
        _atomic_write_json(self.registry_path, self._data)

    def _mutate(self, mutator) -> Any:
        """Exclusive lock, reload, mutate, save. ``mutator`` receives ``self._data``."""
        lock_path = self.registry_path.with_suffix(".json.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                self._reload()
                result = mutator(self._data)
                self.registry_path.write_text(
                    json.dumps(self._data, indent=2, sort_keys=True, default=str) + "\n"
                )
                return result
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    # -- snapshot.json (status diffing) -------------------------------------

    def load_snapshot(self) -> dict[str, Any]:
        if not self.snapshot_path.is_file():
            return {}
        try:
            return json.loads(self.snapshot_path.read_text())
        except json.JSONDecodeError:
            return {}

    def save_snapshot(self, snapshot: dict[str, Any]) -> None:
        _atomic_write_json(self.snapshot_path, snapshot)

    # -- merged_prs.json (Phase 3) --------------------------------------------

    def load_merged_prs(self) -> list[str]:
        import prs

        return prs.load_merged_snapshot(self.merged_prs_path)

    def save_merged_prs(self, keys) -> None:
        import prs

        prs.save_merged_snapshot(self.merged_prs_path, keys)

    # -- jobs ----------------------------------------------------------------

    def new_job(
        self,
        *,
        issue: str,
        kind: str,
        lock_key: str | None,
        workspace: str,
        prompt_class: str,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        now = _now_iso()
        job = {
            "id": job_id,
            "issue": issue,
            "kind": kind,
            "lock_key": lock_key,
            "workspace": workspace,
            "prompt_class": prompt_class,
            "status": "running",
            "attempts": 1,
            "mode": None,
            "model": None,
            "pid": None,
            "request_id": None,
            "chat_id": None,
            "log_path": None,
            "fingerprint": None,
            "target": None,
            "attempt_started_at": now,
            "created_at": now,
            "updated_at": now,
        }
        self.write_job(job)
        return job

    def write_job(self, job: dict[str, Any]) -> dict[str, Any]:
        job["updated_at"] = _now_iso()

        def mutator(data: dict[str, Any]) -> dict[str, Any]:
            data["jobs"][job["id"]] = job
            return job

        self._mutate(mutator)
        (self.jobs_dir / f"{job['id']}.json").write_text(
            json.dumps(job, indent=2, sort_keys=True, default=str) + "\n"
        )
        return job

    def finish_job(
        self, job: dict[str, Any], *, status: str, exit_code: int | None = None
    ) -> dict[str, Any]:
        job["status"] = status
        job["exit_code"] = exit_code
        job["finished_at"] = _now_iso()
        self.write_job(job)
        return job

    def bump_attempt(self, job: dict[str, Any]) -> int:
        """Increment attempts and clear prior-attempt terminal fields."""
        job["attempts"] = job.get("attempts", 1) + 1
        job["status"] = "running"
        job.pop("exit_code", None)
        job.pop("finished_at", None)
        job.pop("error", None)
        job["attempt_started_at"] = _now_iso()
        self.write_job(job)
        return job["attempts"]

    def active_job_for_issue(self, issue: str) -> dict[str, Any] | None:
        self._reload()
        for job in self._data["jobs"].values():
            if job.get("issue") == issue and job.get("status") in ("pending", "running"):
                return job
        return None

    def lock_holder(self, lock_key: str) -> str | None:
        self._reload()
        for job in self._data["jobs"].values():
            if (
                job.get("kind") == "build"
                and job.get("status") in ("pending", "running")
                and job.get("lock_key") == lock_key
            ):
                return job["id"]
        return None

    def running_count(self) -> int:
        self._reload()
        return sum(
            1 for job in self._data["jobs"].values() if job.get("status") in ("pending", "running")
        )

    def reap(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        """Detect finished/stale jobs, finalize them, and return the finished ones."""
        now = now or datetime.now(timezone.utc)
        self._reload()
        reaped: list[dict[str, Any]] = []
        for job in list(self._data["jobs"].values()):
            if job.get("status") not in ("pending", "running"):
                continue
            if job.get("mode") == "headless" and job.get("pid"):
                if not _pid_alive(job["pid"]):
                    status = _infer_log_status(job.get("log_path"))
                    reaped.append(self.finish_job(job, status=status))
            elif job.get("mode") == "worker":
                created = job.get("created_at")
                try:
                    started = datetime.fromisoformat(created) if created else None
                except ValueError:
                    started = None
                if started and (now - started).total_seconds() > STALE_TIMEOUT_SECONDS:
                    reaped.append(self.finish_job(job, status="timeout"))
        return reaped

    # -- escalation latches (status transitions) ------------------------------

    def mark_escalated(self, issue_key: str) -> None:
        def mutator(data: dict[str, Any]) -> None:
            if issue_key not in data["escalated_issues"]:
                data["escalated_issues"].append(issue_key)

        self._mutate(mutator)

    def clear_escalated(self, issue_key: str) -> None:
        def mutator(data: dict[str, Any]) -> None:
            if issue_key in data["escalated_issues"]:
                data["escalated_issues"].remove(issue_key)

        self._mutate(mutator)

    def is_escalated(self, issue_key: str) -> bool:
        self._reload()
        return issue_key in self._data["escalated_issues"]

    # -- risk latches (Phase 5 design_conversation hard-stop) -----------------

    def mark_risk_latched(self, issue_key: str) -> None:
        def mutator(data: dict[str, Any]) -> None:
            data.setdefault("risk_latched_issues", [])
            if issue_key not in data["risk_latched_issues"]:
                data["risk_latched_issues"].append(issue_key)

        self._mutate(mutator)

    def clear_risk_latched(self, issue_key: str) -> None:
        def mutator(data: dict[str, Any]) -> None:
            latched = data.setdefault("risk_latched_issues", [])
            if issue_key in latched:
                latched.remove(issue_key)

        self._mutate(mutator)

    def is_risk_latched(self, issue_key: str) -> bool:
        self._reload()
        return issue_key in self._data.get("risk_latched_issues", [])

    # -- chain (Phase 3: merge-triggered build chain) failures ----------------

    def get_chain_failures(self, parent_key: str) -> int:
        self._reload()
        return int(self._data["chain_failures"].get(parent_key, 0))

    def increment_chain_failures(self, parent_key: str) -> int:
        def mutator(data: dict[str, Any]) -> int:
            value = int(data["chain_failures"].get(parent_key, 0)) + 1
            data["chain_failures"][parent_key] = value
            return value

        return self._mutate(mutator)

    def clear_chain_failures(self, parent_key: str) -> None:
        def mutator(data: dict[str, Any]) -> None:
            if parent_key in data["chain_failures"]:
                del data["chain_failures"][parent_key]

        self._mutate(mutator)

    def is_chain_escalated(self, parent_key: str) -> bool:
        self._reload()
        return parent_key in self._data["chain_escalated"]

    def mark_chain_escalated(self, parent_key: str) -> None:
        def mutator(data: dict[str, Any]) -> None:
            if parent_key not in data["chain_escalated"]:
                data["chain_escalated"].append(parent_key)

        self._mutate(mutator)

    def clear_chain_escalated(self, parent_key: str) -> None:
        def mutator(data: dict[str, Any]) -> None:
            if parent_key in data["chain_escalated"]:
                data["chain_escalated"].remove(parent_key)

        self._mutate(mutator)
