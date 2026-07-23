"""Normalize GitHub Project v2 item status/type and diff snapshots across polls."""

from __future__ import annotations

import re
from typing import Any

STATUS_PATTERNS: dict[str, re.Pattern[str]] = {
    "in_progress": re.compile(r"in[\s_-]*progress", re.IGNORECASE),
    "review_qa": re.compile(r"review\s*/?\s*qa|review[\s_-]*&?[\s_-]*qa|in\s*review", re.IGNORECASE),
    "ready_to_ship": re.compile(r"ready[\s_-]*to[\s_-]*ship|ready[\s_-]*for[\s_-]*deploy", re.IGNORECASE),
    "todo": re.compile(r"to[\s_-]*do|backlog", re.IGNORECASE),
}

# Order matters: more specific patterns (review_qa, ready_to_ship, in_progress)
# must be checked before the broad "todo" fallback.
_STATUS_CHECK_ORDER = ("ready_to_ship", "review_qa", "in_progress", "todo")

ISSUE_TYPE_ALIASES: dict[str, str] = {
    "task": "Task",
    "user story": "User Story",
    "userstory": "User Story",
    "story": "User Story",
    "spec": "Spec",
    "bug": "Bug",
}


def normalize_status(raw: str | None) -> str | None:
    """Map a raw Project Status option name to a canonical status key."""
    if not raw:
        return None
    for key in _STATUS_CHECK_ORDER:
        if STATUS_PATTERNS[key].search(raw):
            return key
    return None


def normalize_issue_type(raw: str | None) -> str | None:
    """Map a raw GitHub issue type name to its canonical label."""
    if not raw:
        return None
    return ISSUE_TYPE_ALIASES.get(raw.strip().lower(), raw.strip())


def task_sub_issue_count(item: dict[str, Any]) -> int:
    """Extract the sub-issue (tracked issues) count from a raw project item.

    Accepts either a project item node (`{"content": {"trackedIssues": ...}}`)
    or the inner issue `content` dict directly.
    """
    content = item.get("content") if isinstance(item.get("content"), dict) else item
    tracked = content.get("trackedIssues") or content.get("subIssues") or {}
    return int(tracked.get("totalCount") or 0)


def snapshot_from_items(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build a `repo#number` keyed snapshot from fetch.py's item list."""
    snapshot: dict[str, dict[str, Any]] = {}
    for item in items:
        key = f"{item['repo']}#{item['number']}"
        snapshot[key] = {
            "repo": item["repo"],
            "number": item["number"],
            "url": item.get("url"),
            "title": item.get("title"),
            "status": item.get("status"),
            "issue_type": item.get("issue_type"),
            "parent_number": item.get("parent_number"),
            "task_sub_issue_count": item.get("task_sub_issue_count"),
        }
    return snapshot


def diff_snapshots(
    previous: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return transitions for items whose status changed between snapshots.

    A brand-new item (not in `previous`) has `from_status=None`.
    """
    transitions: list[dict[str, Any]] = []
    for key, item in current.items():
        prev_item = previous.get(key)
        from_status = prev_item["status"] if prev_item else None
        to_status = item["status"]
        if from_status == to_status:
            continue
        transitions.append(
            {
                "issue": key,
                "repo": item["repo"],
                "number": item["number"],
                "url": item.get("url"),
                "title": item.get("title"),
                "issue_type": item.get("issue_type"),
                "from_status": from_status,
                "to_status": to_status,
                "parent_number": item.get("parent_number"),
                "task_sub_issue_count": item.get("task_sub_issue_count"),
            }
        )
    return transitions
