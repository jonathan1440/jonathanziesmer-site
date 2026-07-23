"""Atomic fingerprint memory for Phase 4 maintenance jobs.

Layout under ``state_dir/memory/<task>/``:

- ``<fingerprint>.json``  — success receipt (known-good)
- ``<fingerprint>.claim`` — exclusive lease while work is in flight
- ``last_run.json``       — checkpoint of last due evaluation

Claims use ``O_CREAT | O_EXCL``; receipts use temp-file + ``os.replace``.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from config import ensure_dir

ClaimResult = Literal["acquired", "known_good", "busy"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(task: str, inputs: dict[str, Any], policy_version: int | str) -> str:
    """Deterministic SHA-256 of task + policy_version + canonical inputs."""
    payload = {
        "task": task,
        "policy_version": policy_version,
        "inputs": inputs,
    }
    digest = sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return digest[:32]


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True, default=str)
            f.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class MemoryStore:
    """File-backed claim / receipt store under ``state_dir/memory``."""

    def __init__(self, state_dir: Path | str) -> None:
        self.state_dir = Path(state_dir)
        self.root = ensure_dir(self.state_dir / "memory")

    def task_dir(self, task: str) -> Path:
        safe = task.replace("/", "_").replace(" ", "_")
        return ensure_dir(self.root / safe)

    def receipt_path(self, task: str, fp: str) -> Path:
        return self.task_dir(task) / f"{fp}.json"

    def claim_path(self, task: str, fp: str) -> Path:
        return self.task_dir(task) / f"{fp}.claim"

    def last_run_path(self, task: str) -> Path:
        return self.task_dir(task) / "last_run.json"

    def has_receipt(self, task: str, fp: str) -> bool:
        data = _read_json(self.receipt_path(task, fp))
        return bool(data and data.get("status") == "known_good")

    def claim(
        self,
        task: str,
        fp: str,
        *,
        ttl_seconds: int,
        now: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ClaimResult:
        """Acquire an exclusive lease for ``(task, fingerprint)``.

        Returns:
            ``known_good`` — success receipt already exists
            ``busy`` — another live claim holds the lease
            ``acquired`` — this caller now owns the lease
        """
        now = now or datetime.now(timezone.utc)
        if self.has_receipt(task, fp):
            return "known_good"

        claim_path = self.claim_path(task, fp)
        if claim_path.is_file():
            existing = _read_json(claim_path) or {}
            started = _parse_iso(existing.get("started_at"))
            if started is not None and (now - started).total_seconds() < ttl_seconds:
                return "busy"
            # Stale claim — remove and re-acquire.
            try:
                claim_path.unlink()
            except OSError:
                return "busy"

        payload = {
            "task": task,
            "fingerprint": fp,
            "started_at": now.isoformat(),
            "ttl_seconds": ttl_seconds,
            "metadata": metadata or {},
        }
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(str(claim_path), flags, 0o644)
        except FileExistsError:
            return "busy"
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True, default=str)
                f.write("\n")
        except Exception:
            try:
                claim_path.unlink()
            except OSError:
                pass
            raise
        return "acquired"

    def complete(
        self,
        task: str,
        fp: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Write a known-good receipt and drop any claim."""
        receipt = {
            "task": task,
            "fingerprint": fp,
            "status": "known_good",
            "completed_at": _now_iso(),
            "metadata": metadata or {},
        }
        _atomic_write_json(self.receipt_path(task, fp), receipt)
        self.release_claim(task, fp)

    def fail(
        self,
        task: str,
        fp: str,
        *,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Release the claim without creating a known-good receipt."""
        failure_path = self.task_dir(task) / f"{fp}.failed.json"
        _atomic_write_json(
            failure_path,
            {
                "task": task,
                "fingerprint": fp,
                "status": "failed",
                "failed_at": _now_iso(),
                "error": error,
                "metadata": metadata or {},
            },
        )
        self.release_claim(task, fp)

    def release_claim(self, task: str, fp: str) -> None:
        path = self.claim_path(task, fp)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def last_run(self, task: str) -> datetime | None:
        data = _read_json(self.last_run_path(task))
        if not data:
            return None
        return _parse_iso(data.get("last_run_at"))

    def mark_last_run(self, task: str, when: datetime | None = None) -> None:
        when = when or datetime.now(timezone.utc)
        _atomic_write_json(
            self.last_run_path(task),
            {"task": task, "last_run_at": when.isoformat()},
        )
