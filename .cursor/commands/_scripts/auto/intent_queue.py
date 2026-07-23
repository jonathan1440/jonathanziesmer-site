"""Durable pending-intent queue under ``state_dir/queue/``.

When concurrency or locks block admission, intents are persisted so a later
``dispatch_once`` can admit them without relying on Status re-transitions
(snapshot already advanced).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import ensure_dir


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IntentQueue:
    """File-backed FIFO of dispatch intents."""

    def __init__(self, state_dir: Path | str) -> None:
        self.state_dir = ensure_dir(state_dir)
        self.queue_dir = ensure_dir(self.state_dir / "queue")

    def enqueue(
        self,
        *,
        kind: str,
        prompt_class: str,
        lock_key: str | None,
        transition: dict[str, Any],
        issue: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        intent_id = uuid.uuid4().hex[:12]
        issue_key = issue or transition.get("issue") or ""
        # Dedup: one pending intent per issue+kind
        for existing in self.list_pending():
            if (
                existing.get("issue") == issue_key
                and existing.get("kind") == kind
                and existing.get("status") == "pending"
            ):
                return existing

        intent = {
            "id": intent_id,
            "status": "pending",
            "kind": kind,
            "prompt_class": prompt_class,
            "lock_key": lock_key,
            "issue": issue_key,
            "transition": transition,
            "metadata": metadata or {},
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        self._write(intent)
        return intent

    def list_pending(self) -> list[dict[str, Any]]:
        intents: list[dict[str, Any]] = []
        for path in sorted(self.queue_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("status") == "pending":
                intents.append(data)
        intents.sort(key=lambda i: i.get("created_at") or "")
        return intents

    def mark_done(self, intent_id: str) -> None:
        path = self.queue_dir / f"{intent_id}.json"
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            path.unlink(missing_ok=True)
            return
        data["status"] = "done"
        data["updated_at"] = _now_iso()
        path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")

    def mark_cancelled(self, intent_id: str, *, reason: str = "") -> None:
        path = self.queue_dir / f"{intent_id}.json"
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            path.unlink(missing_ok=True)
            return
        data["status"] = "cancelled"
        data["reason"] = reason
        data["updated_at"] = _now_iso()
        path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")

    def _write(self, intent: dict[str, Any]) -> None:
        path = self.queue_dir / f"{intent['id']}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(intent, indent=2, sort_keys=True, default=str) + "\n")
        tmp.replace(path)
