"""Append-only NDJSON run log under a log directory.

Schema version 1 adds lifecycle events:

- ``run_started`` / ``run_finished`` with job/attempt IDs, kind, prompt class,
  backend mode, model, request_id, status, exit_code, duration_seconds

Legacy events (``spawn``, ``reap``, …) remain valid; readers skip unknown or
malformed rows.

Construct with a ``log_dir`` path (not the whole config):

    run_log = RunLog(log_dir)
    run_log.write({"event": "run_started", "job_id": job["id"], ...})
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from config import ensure_dir

SCHEMA_VERSION = 1


class RunLog:
    """One NDJSON file per UTC day under ``log_dir``."""

    def __init__(
        self,
        log_dir: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.log_dir = ensure_dir(log_dir)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _path_for(self, when: datetime) -> Path:
        return self.log_dir / f"{when.strftime('%Y-%m-%d')}.ndjson"

    def path_for_date(self, day: date | str) -> Path:
        if isinstance(day, str):
            day = date.fromisoformat(day)
        return self.log_dir / f"{day.isoformat()}.ndjson"

    def write(self, record: dict[str, Any], *, ts: datetime | None = None) -> dict[str, Any]:
        """Append one record. ``ts`` overrides the clock when provided."""
        when = ts or self._clock()
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        payload = {"schema_version": SCHEMA_VERSION, "ts": when.isoformat(), **record}
        path = self._path_for(when)
        with open(path, "a") as f:
            f.write(json.dumps(payload, default=str) + "\n")
        return payload

    def read_day(self, day: date | str) -> list[dict[str, Any]]:
        """Read all well-formed records for a UTC day. Skips bad lines."""
        path = self.path_for_date(day)
        if not path.is_file():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                records.append(data)
        return records

    def read_range(self, start: date | str, end: date | str) -> list[dict[str, Any]]:
        """Inclusive UTC date range of records."""
        if isinstance(start, str):
            start = date.fromisoformat(start)
        if isinstance(end, str):
            end = date.fromisoformat(end)
        records: list[dict[str, Any]] = []
        cur = start
        while cur <= end:
            records.extend(self.read_day(cur))
            cur += timedelta(days=1)
        return records


def attempt_run_id(job_id: str, attempt: int) -> str:
    """Stable ``<job_id>:<attempt>`` identifier for lifecycle pairing."""
    return f"{job_id}:{attempt}"


def run_started_record(job: dict[str, Any], *, model: str | None = None) -> dict[str, Any]:
    """Build a ``run_started`` event from a job dict."""
    attempt = int(job.get("attempts") or 1)
    return {
        "event": "run_started",
        "run_id": attempt_run_id(job["id"], attempt),
        "job_id": job["id"],
        "attempt": attempt,
        "kind": job.get("kind"),
        "prompt_class": job.get("prompt_class"),
        "issue": job.get("issue"),
        "url": job.get("url"),
        "pr": job.get("pr"),
        "request_id": job.get("request_id"),
        "model": model if model is not None else job.get("model"),
        "mode": job.get("mode"),
        "fingerprint": job.get("fingerprint"),
        "target": job.get("target") or job.get("issue"),
    }


def run_finished_record(
    job: dict[str, Any],
    *,
    status: str,
    exit_code: int | None = None,
    duration_seconds: float | None = None,
    outcome_known: bool = True,
) -> dict[str, Any]:
    """Build a ``run_finished`` event from a job dict."""
    attempt = int(job.get("attempts") or 1)
    return {
        "event": "run_finished",
        "run_id": attempt_run_id(job["id"], attempt),
        "job_id": job["id"],
        "attempt": attempt,
        "kind": job.get("kind"),
        "prompt_class": job.get("prompt_class"),
        "issue": job.get("issue"),
        "url": job.get("url"),
        "pr": job.get("pr"),
        "request_id": job.get("request_id"),
        "model": job.get("model"),
        "mode": job.get("mode"),
        "fingerprint": job.get("fingerprint"),
        "target": job.get("target") or job.get("issue"),
        "status": status,
        "exit_code": exit_code,
        "duration_seconds": duration_seconds,
        "outcome_known": outcome_known,
    }
