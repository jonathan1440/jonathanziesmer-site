"""Classify Project status transitions into dispatchable work.

Capacity, locks, and risk latches are enforced by ``admission.py`` so rejected
work can be durably queued. This module still skips escalated issues and
issues that already have an active job.
"""

from __future__ import annotations

from typing import Any

DISPATCH_KINDS = frozenset(
    {
        "build",
        "review_resolve",
        "plan",
        "review_resolve_2cycle",
        "post_merge",
        "goal_approve",
        "risk_classify",
        "resolve",
    }
)


def lock_key_for(transition: dict[str, Any], kind: str) -> str:
    """Build key: builds lock on the parent story via `repo+parent#N`; everything
    else (including a build with no parent) locks on the issue itself via
    `repo+issue`."""
    repo = transition.get("repo") or "unknown"
    if kind == "build":
        parent = transition.get("parent_number")
        if parent:
            return f"{repo}+parent#{parent}"
        return f"{repo}+{transition.get('issue')}"
    return f"{repo}+{transition.get('issue')}"


def classify_transition(transition: dict[str, Any]) -> str | None:
    """Map a status transition to a dispatch kind, or None if it isn't actionable.

    - Task todo -> in_progress (not a cold/new appearance) => build
    - Task -> review_qa (not cold) => review_resolve
    - User Story todo -> in_progress with task_sub_issue_count == 0 => plan
    - User Story / Spec -> review_qa (not cold) => review_resolve_2cycle
    - Spec todo -> in_progress with goal_id (Phase 5) => goal_approve
    - Spec -> in_progress without goal => ignored (derived)
    """
    from_status = transition.get("from_status")
    to_status = transition.get("to_status")
    issue_type = transition.get("issue_type")

    if from_status is None:
        # Item just appeared on the board; not a transition we act on.
        return None

    if issue_type == "Task":
        if from_status == "todo" and to_status == "in_progress":
            return "build"
        if to_status == "review_qa":
            return "review_resolve"
        return None

    if issue_type == "User Story":
        if (
            from_status == "todo"
            and to_status == "in_progress"
            and transition.get("task_sub_issue_count") == 0
        ):
            return "plan"
        if to_status == "review_qa":
            return "review_resolve_2cycle"
        return None

    if issue_type == "Spec":
        if from_status == "todo" and to_status == "in_progress":
            if transition.get("goal_id") or transition.get("has_goal"):
                return "goal_approve"
            return None
        if to_status == "review_qa":
            return "review_resolve_2cycle"
        return None

    return None


def _prompt_class_for(kind: str) -> str:
    return kind


def filter_transitions(
    transitions: list[dict[str, Any]],
    *,
    registry,
    concurrency: int,
    enqueue_on_cap: bool = True,
) -> list[dict[str, Any]]:
    """Classify transitions and admit as many as fit within `concurrency`.

    When ``enqueue_on_cap`` is False, concurrency and build-lock limits are not
    applied here — callers (dispatch + admission) queue overflow intents.

    Returns a list of {transition, kind, lock_key, prompt_class}.
    """
    admitted: list[dict[str, Any]] = []
    slots_used = registry.running_count()
    locks_claimed_this_cycle: set[str] = set()

    for transition in transitions:
        kind = classify_transition(transition)
        if kind is None:
            continue

        issue_key = transition["issue"]
        if registry.is_escalated(issue_key):
            continue
        if hasattr(registry, "is_risk_latched") and registry.is_risk_latched(issue_key):
            continue
        if registry.active_job_for_issue(issue_key):
            continue

        lock_key = lock_key_for(transition, kind)
        if enqueue_on_cap and kind == "build":
            if registry.lock_holder(lock_key) is not None:
                continue
            if lock_key in locks_claimed_this_cycle:
                continue

        if enqueue_on_cap and slots_used >= concurrency:
            continue

        admitted.append(
            {
                "transition": transition,
                "kind": kind,
                "lock_key": lock_key,
                "prompt_class": _prompt_class_for(kind),
            }
        )
        slots_used += 1
        if kind == "build":
            locks_claimed_this_cycle.add(lock_key)

    return admitted


def filter_post_merge_events(
    events: list[dict[str, Any]],
    *,
    registry,
    concurrency: int,
    reserved: int = 0,
    enqueue_on_cap: bool = True,
) -> list[dict[str, Any]]:
    """Admit resolved `spec_pr_merged` events as `post_merge` actionables.

    Each event is expected to already carry the resolved Spec issue fields:
    `issue`, `repo`, `number`, `url`, `title`.
    """
    admitted: list[dict[str, Any]] = []
    slots_used = registry.running_count() + reserved

    for event in events:
        transition = {
            "issue": event["issue"],
            "repo": event["repo"],
            "number": event["number"],
            "url": event.get("url"),
            "title": event.get("title"),
            "issue_type": "Spec",
            "from_status": None,
            "to_status": "merged",
            "parent_number": None,
            "task_sub_issue_count": 0,
            "pr": event.get("pr"),
            "merged_at": event.get("merged_at"),
        }

        issue_key = transition["issue"]
        if registry.is_escalated(issue_key):
            continue
        if hasattr(registry, "is_risk_latched") and registry.is_risk_latched(issue_key):
            continue
        if registry.active_job_for_issue(issue_key):
            continue

        if enqueue_on_cap and slots_used >= concurrency:
            continue

        lock_key = lock_key_for(transition, "post_merge")
        admitted.append(
            {
                "transition": transition,
                "kind": "post_merge",
                "lock_key": lock_key,
                "prompt_class": "post_merge",
            }
        )
        slots_used += 1

    return admitted
