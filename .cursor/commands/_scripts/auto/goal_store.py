"""Durable goal records for Phase 5 orchestrator under ``state_dir/goals/``."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import ensure_dir

GOAL_STATUSES = frozenset(
    {
        "awaiting_approval",
        "running",
        "blocked",
        "completed",
        "failed",
        "cancelled",
    }
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GoalStore:
    """File-backed goals keyed by goal id and Spec issue."""

    def __init__(self, state_dir: Path | str) -> None:
        self.state_dir = ensure_dir(state_dir)
        self.goals_dir = ensure_dir(self.state_dir / "goals")
        self.index_path = self.state_dir / "goals_index.json"
        self._index = self._load_index()

    def _load_index(self) -> dict[str, Any]:
        if not self.index_path.is_file():
            return {"by_spec": {}, "by_id": {}}
        try:
            data = json.loads(self.index_path.read_text())
        except json.JSONDecodeError:
            return {"by_spec": {}, "by_id": {}}
        data.setdefault("by_spec", {})
        data.setdefault("by_id", {})
        return data

    def _save_index(self) -> None:
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._index, indent=2, sort_keys=True) + "\n")
        tmp.replace(self.index_path)

    def _path(self, goal_id: str) -> Path:
        return self.goals_dir / f"{goal_id}.json"

    def create(
        self,
        *,
        goal_text: str,
        spec_issue: str,
        spec_url: str | None = None,
        title: str = "",
        stories: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        goal_id = uuid.uuid4().hex[:12]
        now = _now_iso()
        record = {
            "id": goal_id,
            "goal_text": goal_text,
            "title": title or goal_text[:80],
            "spec_issue": spec_issue,
            "spec_url": spec_url,
            "status": "awaiting_approval",
            "stories": stories or [],
            "story_issues": [],
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }
        self.write(record)
        self._index["by_id"][goal_id] = spec_issue
        self._index["by_spec"][spec_issue] = goal_id
        self._save_index()
        return record

    def write(self, record: dict[str, Any]) -> dict[str, Any]:
        record["updated_at"] = _now_iso()
        path = self._path(record["id"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, indent=2, sort_keys=True, default=str) + "\n")
        tmp.replace(path)
        return record

    def get(self, goal_id: str) -> dict[str, Any] | None:
        path = self._path(goal_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return None

    def get_by_spec(self, spec_issue: str) -> dict[str, Any] | None:
        goal_id = self._index.get("by_spec", {}).get(spec_issue)
        if not goal_id:
            # Reload index in case another process wrote it.
            self._index = self._load_index()
            goal_id = self._index.get("by_spec", {}).get(spec_issue)
        if not goal_id:
            return None
        return self.get(goal_id)

    def set_status(self, goal_id: str, status: str) -> dict[str, Any]:
        if status not in GOAL_STATUSES:
            raise ValueError(f"invalid goal status: {status!r}")
        record = self.get(goal_id)
        if record is None:
            raise KeyError(goal_id)
        record["status"] = status
        return self.write(record)

    def list_goals(self) -> list[dict[str, Any]]:
        goals: list[dict[str, Any]] = []
        for path in sorted(self.goals_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                goals.append(data)
        return goals
