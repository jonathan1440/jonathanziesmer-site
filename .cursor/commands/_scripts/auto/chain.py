"""Merge-triggered build chain: pick the next unblocked Task after a task PR merges."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import escalate

_SCRIPT_DIR = Path(__file__).resolve().parent
_GH_SCRIPTS_DIR = _SCRIPT_DIR.parent / "gh"

_ISSUE_URL_PATTERN = re.compile(r"github\.com/([^/]+/[^/]+)/issues/(\d+)")


def _load_gh_build_publish():
    module_name = "gh_build_publish_for_auto"
    if module_name in sys.modules:
        return sys.modules[module_name]
    path = _GH_SCRIPTS_DIR / "gh-build-publish.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _default_blocker_check(body: str) -> bool:
    module = _load_gh_build_publish()
    blockers = module.parse_blockers(body or "")
    return module.check_blockers(blockers)["passed"]


def _default_issue_details(repo: str, number: int) -> dict[str, Any]:
    result = subprocess.run(
        ["gh", "issue", "view", str(number), "--repo", repo, "--json", "body,state"],
        check=True,
        capture_output=True,
        text=True,
    )
    import json

    data = json.loads(result.stdout)
    return {"body": data.get("body") or "", "state": data.get("state") or "OPEN"}


def _parse_issue_url(url: str | None) -> tuple[str, int] | None:
    match = _ISSUE_URL_PATTERN.search(url or "")
    if not match:
        return None
    return match.group(1), int(match.group(2))


def _default_set_status(project: dict[str, Any], url: str, status_key: str) -> dict[str, Any]:
    module = _load_gh_build_publish()
    parsed = _parse_issue_url(url)
    if not parsed:
        return {"ok": False, "warn": f"could not parse issue url: {url}"}
    repo, number = parsed
    resolved = module.resolve_project_from_issue_graphql(repo, number)
    if not resolved:
        return {"ok": False, "warn": f"could not resolve project for {repo}#{number}"}
    return module.set_project_status(resolved, url, status_key)


def _resolve_task_item(event: dict[str, Any], items: dict[str, Any]) -> dict[str, Any] | None:
    for ref in event.get("closing_issues", []):
        item = items.get(ref)
        if item and item.get("issue_type") == "Task":
            return item
    return None


def record_chain_failure(registry, parent_key: str) -> int:
    return registry.increment_chain_failures(parent_key)


def chain_failure_count(registry, parent_key: str) -> int:
    return registry.get_chain_failures(parent_key)


def clear_chain_failures(registry, parent_key: str) -> None:
    registry.clear_chain_failures(parent_key)


def kick_next(
    event: dict[str, Any],
    *,
    cfg: dict[str, Any],
    registry,
    items: dict[str, Any],
    project: dict[str, Any] | None = None,
    blocker_check_fn: Callable[[str], bool] | None = None,
    issue_details_fn: Callable[[str, int], dict[str, Any]] | None = None,
    set_status_fn: Callable[..., dict[str, Any]] | None = None,
    escalate_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """After a `task_pr_merged` event, kick the lowest-numbered eligible unblocked
    sibling Task under the same parent story, subject to locks and the chain
    failure budget.

    `parent_key` and the build lock key share the same `repo+parent#N` format
    used by `filter.lock_key_for`.

    Returns one of:
    - {"action": "idle", "reason": ..., ...}
    - {"action": "locked", "lock_key": ..., "parent_key": ...}
    - {"action": "budget_exhausted", "parent_key": ...}
    - {"action": "kick", "transition": {...}, "parent_key": ...}
    """
    blocker_check_fn = blocker_check_fn or _default_blocker_check
    issue_details_fn = issue_details_fn or _default_issue_details
    set_status_fn = set_status_fn or _default_set_status
    escalate_fn = escalate_fn or escalate.escalate_issue

    task_item = _resolve_task_item(event, items)
    if not task_item:
        return {"action": "idle", "reason": "no_task_found", "event": event}

    parent_number = task_item.get("parent_number")
    if not parent_number:
        return {"action": "idle", "reason": "no_parent", "event": event}

    repo = task_item["repo"]
    parent_key = f"{repo}+parent#{parent_number}"

    siblings = sorted(
        (
            item
            for item in items.values()
            if item.get("repo") == repo
            and item.get("issue_type") == "Task"
            and item.get("parent_number") == parent_number
        ),
        key=lambda i: i["number"],
    )

    eligible: list[dict[str, Any]] = []
    for item in siblings:
        issue_key = item["issue"]
        if item.get("status") != "todo":
            continue
        if registry.is_escalated(issue_key):
            continue
        if registry.active_job_for_issue(issue_key):
            continue
        details = issue_details_fn(repo, item["number"])
        if details.get("state") != "OPEN":
            continue
        if not blocker_check_fn(details.get("body") or ""):
            continue
        eligible.append(item)

    if not eligible:
        return {
            "action": "idle",
            "reason": "no_eligible_task",
            "parent_key": parent_key,
            "event": event,
        }

    if registry.lock_holder(parent_key) is not None:
        return {"action": "locked", "lock_key": parent_key, "parent_key": parent_key, "event": event}

    budget = cfg.get("chain_failure_budget", 3)
    if registry.get_chain_failures(parent_key) >= budget:
        if not registry.is_chain_escalated(parent_key):
            escalate_fn(
                f"{repo}#{parent_number}",
                reason=(
                    f"Auto-workflow chain stopped: {budget} consecutive build "
                    f"failures under this story. Manual intervention needed."
                ),
                owner_mention=cfg.get("escalate_owner") or "",
            )
            registry.mark_chain_escalated(parent_key)
        return {"action": "budget_exhausted", "parent_key": parent_key, "event": event}

    chosen = eligible[0]
    set_status_fn(project or {}, chosen["url"], "in_progress")

    transition = {
        "issue": chosen["issue"],
        "repo": repo,
        "number": chosen["number"],
        "url": chosen.get("url"),
        "title": chosen.get("title"),
        "issue_type": "Task",
        "from_status": "todo",
        "to_status": "in_progress",
        "parent_number": parent_number,
        "task_sub_issue_count": 0,
    }
    return {"action": "kick", "transition": transition, "parent_key": parent_key, "event": event}
