"""Completion-on-merge helpers (Phase 5).

Parent Spec / User Story / normal Task issues complete only after their PR
merge is observed. Review-finding Bug/Task issues complete when their
finding PR merges (agent-merge allowed).
"""

from __future__ import annotations

from typing import Any

from merge_policy import is_finding_issue


def issue_completion_policy(
    *,
    issue_type: str | None,
    is_review_finding: bool = False,
    labels: list[str] | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Return how an issue may be marked complete."""
    if is_finding_issue(
        issue_type=issue_type,
        labels=labels,
        is_review_finding=is_review_finding,
        branch=branch,
    ):
        return {
            "requires_merged_pr": True,
            "agent_may_merge": True,
            "close_on_merge": True,
            "kind": "finding",
        }
    itype = (issue_type or "").strip()
    if itype in {"Spec", "User Story", "Task"}:
        return {
            "requires_merged_pr": True,
            "agent_may_merge": False,
            "close_on_merge": False,  # medium tier / human staging for Spec; Ready to ship first
            "kind": "parent",
        }
    return {
        "requires_merged_pr": True,
        "agent_may_merge": False,
        "close_on_merge": False,
        "kind": "unknown",
    }


def should_mark_ready_to_ship(
    *,
    issue_type: str | None,
    parent_pr_merged: bool,
    open_finding_prs: int = 0,
) -> dict[str, Any]:
    """Parent Ready-to-ship only when findings are merged and parent PR still open.

    ``parent_pr_merged`` must be False for Ready to ship (human still reviews).
    After parent merge, completion is a separate human/staging step for Specs.
    """
    if open_finding_prs > 0:
        return {"ok": False, "reason": "open_finding_prs"}
    if parent_pr_merged:
        return {"ok": False, "reason": "parent_already_merged"}
    if (issue_type or "").strip() not in {"Task", "User Story", "Spec"}:
        return {"ok": False, "reason": "unsupported_issue_type"}
    return {"ok": True, "reason": "findings_merged_parent_open"}
