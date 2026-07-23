"""PR merge allowlist for auto-workflow agents (Phase 5).

Agents may merge only review-generated Bug/Task *finding* PRs.
Spec, User Story, and normal Task PRs are human-merge only.
"""

from __future__ import annotations

from typing import Any

# Issue types whose PRs agents must never merge.
HUMAN_ONLY_ISSUE_TYPES = frozenset({"Spec", "User Story", "Task"})

# Finding issues created by /gh-review (Bug or Task follow-ups under resolve).
AGENT_MERGEABLE_FINDING_TYPES = frozenset({"Bug", "Task"})


def is_finding_issue(
    *,
    issue_type: str | None,
    labels: list[str] | None = None,
    parent_issue_type: str | None = None,
    is_review_finding: bool = False,
    branch: str | None = None,
) -> bool:
    """Return True when this issue is a review finding eligible for agent merge.

    A finding is a Bug (always) or a Task that is explicitly marked as a review
    finding (``is_review_finding`` / ``rr-*`` label / ``bug/`` or ``finding/`` branch).
    Normal Task issues under a story are NOT findings.
    """
    labels = [str(x).lower() for x in (labels or [])]
    itype = (issue_type or "").strip()

    if itype == "Bug":
        return True

    if is_review_finding:
        return itype in AGENT_MERGEABLE_FINDING_TYPES

    if any(lbl.startswith("rr-") or lbl in {"review-finding", "gh-review-finding"} for lbl in labels):
        return itype in AGENT_MERGEABLE_FINDING_TYPES

    if branch and (
        branch.startswith("bug/")
        or branch.startswith("finding/")
        or "/rr-" in branch
        or branch.startswith("fix/")
    ):
        return itype in AGENT_MERGEABLE_FINDING_TYPES

    return False


def can_agent_merge_pr(
    *,
    issue_type: str | None,
    labels: list[str] | None = None,
    parent_issue_type: str | None = None,
    is_review_finding: bool = False,
    branch: str | None = None,
    pr_title: str | None = None,
) -> dict[str, Any]:
    """Decide whether an agent is allowed to merge this PR.

    Returns ``{allowed: bool, reason: str}``.
    """
    itype = (issue_type or "").strip()

    if itype == "Spec":
        return {"allowed": False, "reason": "spec_pr_human_only"}
    if itype == "User Story":
        return {"allowed": False, "reason": "story_pr_human_only"}

    if is_finding_issue(
        issue_type=itype,
        labels=labels,
        parent_issue_type=parent_issue_type,
        is_review_finding=is_review_finding,
        branch=branch,
    ):
        return {"allowed": True, "reason": "review_finding_pr"}

    if itype == "Task":
        return {"allowed": False, "reason": "normal_task_pr_human_only"}

    # Unknown types: deny.
    return {"allowed": False, "reason": f"unknown_or_denied_type:{itype or 'empty'}"}


def assert_agent_may_merge(**kwargs: Any) -> None:
    """Raise ``PermissionError`` when merge is not allowed."""
    decision = can_agent_merge_pr(**kwargs)
    if not decision["allowed"]:
        raise PermissionError(f"agent merge denied: {decision['reason']}")
