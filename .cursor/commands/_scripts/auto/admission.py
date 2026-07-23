"""Shared admission gate for board dispatch, maintenance, and orchestrator.

All spawns must go through ``admit_and_spawn`` (or ``evaluate`` + caller spawn)
so concurrency, locks, escalation, and risk latches are enforced in one place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import filter as dispatch_filter
import prompts
import runner
from intent_queue import IntentQueue


class AdmissionDecision:
    """Result of evaluating whether a job may spawn now."""

    def __init__(
        self,
        *,
        admitted: bool,
        reason: str = "",
        enqueue: bool = False,
    ) -> None:
        self.admitted = admitted
        self.reason = reason
        self.enqueue = enqueue

    def __repr__(self) -> str:
        return (
            f"AdmissionDecision(admitted={self.admitted!r}, "
            f"reason={self.reason!r}, enqueue={self.enqueue!r})"
        )


def evaluate(
    *,
    registry,
    kind: str,
    issue: str | None,
    lock_key: str | None,
    concurrency: int,
    reserved: int = 0,
) -> AdmissionDecision:
    """Return whether a new job may start under current registry state."""
    if issue and registry.is_escalated(issue):
        return AdmissionDecision(admitted=False, reason="escalated")
    if issue and registry.is_risk_latched(issue):
        return AdmissionDecision(admitted=False, reason="risk_latched")
    if issue and registry.active_job_for_issue(issue):
        return AdmissionDecision(admitted=False, reason="active_job")

    if kind == "build" and lock_key and registry.lock_holder(lock_key) is not None:
        return AdmissionDecision(admitted=False, reason="lock_held", enqueue=True)

    if registry.running_count() + reserved >= concurrency:
        return AdmissionDecision(admitted=False, reason="concurrency", enqueue=True)

    return AdmissionDecision(admitted=True)


def admit_and_spawn(
    *,
    cfg: dict[str, Any],
    registry,
    run_log,
    workspace: Path | str,
    log_dir: Path | str,
    kind: str,
    prompt_class: str,
    transition: dict[str, Any],
    lock_key: str | None = None,
    intent_queue: IntentQueue | None = None,
    job_extras: dict[str, Any] | None = None,
    spawn_headless_fn: Callable[..., dict[str, Any]] | None = None,
    spawn_worker_fn: Callable[..., dict[str, Any]] | None = None,
    reserved: int = 0,
) -> dict[str, Any]:
    """Evaluate, optionally enqueue, create job, and spawn.

    Returns a result dict::

        {"status": "spawned"|"queued"|"skipped", "job": ..., "intent": ..., "reason": ...}
    """
    issue = transition.get("issue")
    if lock_key is None:
        lock_key = dispatch_filter.lock_key_for(transition, kind)

    decision = evaluate(
        registry=registry,
        kind=kind,
        issue=issue,
        lock_key=lock_key,
        concurrency=int(cfg["concurrency"]),
        reserved=reserved,
    )

    if not decision.admitted:
        intent = None
        if decision.enqueue and intent_queue is not None:
            intent = intent_queue.enqueue(
                kind=kind,
                prompt_class=prompt_class,
                lock_key=lock_key,
                transition=transition,
                issue=issue,
            )
            if run_log is not None:
                run_log.write(
                    {
                        "event": "intent_queued",
                        "intent_id": intent["id"],
                        "kind": kind,
                        "issue": issue,
                        "reason": decision.reason,
                    }
                )
            return {
                "status": "queued",
                "reason": decision.reason,
                "intent": intent,
                "job": None,
            }
        return {
            "status": "skipped",
            "reason": decision.reason,
            "intent": None,
            "job": None,
        }

    prompt = prompts.build_prompt(prompt_class, transition)
    job = registry.new_job(
        issue=issue or f"anonymous:{kind}",
        kind=kind,
        lock_key=lock_key,
        workspace=str(workspace),
        prompt_class=prompt_class,
    )
    job["url"] = transition.get("url")
    job["title"] = transition.get("title")
    job["repo"] = transition.get("repo")
    job["number"] = transition.get("number")
    job["parent_number"] = transition.get("parent_number")
    job["pr"] = transition.get("pr")
    if job_extras:
        job.update(job_extras)

    try:
        runner.spawn_for_job(
            job,
            prompt,
            cfg,
            workspace,
            log_dir,
            spawn_headless_fn=spawn_headless_fn or runner.spawn_headless,
            spawn_worker_fn=spawn_worker_fn or runner.spawn_worker,
            run_log=run_log,
        )
        registry.write_job(job)
        if run_log is not None:
            run_log.write(
                {
                    "event": "spawn",
                    "job_id": job["id"],
                    "kind": kind,
                    "issue": issue,
                    "request_id": job.get("request_id"),
                    "model": job.get("model"),
                    "mode": job.get("mode"),
                    "prompt_class": prompt_class,
                }
            )
        return {"status": "spawned", "job": job, "intent": None, "reason": ""}
    except Exception as exc:  # noqa: BLE001
        job["error"] = str(exc)
        runner.finish_and_log(
            job,
            registry=registry,
            run_log=run_log,
            status="failed",
            exit_code=None,
            outcome_known=True,
        )
        if run_log is not None:
            run_log.write({"event": "spawn_error", "job_id": job["id"], "error": str(exc)})
        return {
            "status": "spawn_error",
            "job": job,
            "intent": None,
            "reason": str(exc),
        }


def drain_queue(
    *,
    cfg: dict[str, Any],
    registry,
    run_log,
    workspace: Path | str,
    log_dir: Path | str,
    intent_queue: IntentQueue,
    spawn_headless_fn: Callable[..., dict[str, Any]] | None = None,
    spawn_worker_fn: Callable[..., dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Try to admit pending intents in FIFO order. Returns spawn results."""
    results: list[dict[str, Any]] = []
    for intent in intent_queue.list_pending():
        decision = evaluate(
            registry=registry,
            kind=intent["kind"],
            issue=intent.get("issue"),
            lock_key=intent.get("lock_key"),
            concurrency=int(cfg["concurrency"]),
        )
        if not decision.admitted:
            if decision.reason in ("escalated", "risk_latched"):
                intent_queue.mark_cancelled(intent["id"], reason=decision.reason)
            continue

        result = admit_and_spawn(
            cfg=cfg,
            registry=registry,
            run_log=run_log,
            workspace=workspace,
            log_dir=log_dir,
            kind=intent["kind"],
            prompt_class=intent["prompt_class"],
            transition=intent.get("transition") or {},
            lock_key=intent.get("lock_key"),
            intent_queue=None,  # already queued; do not re-enqueue
            job_extras=intent.get("metadata") or None,
            spawn_headless_fn=spawn_headless_fn,
            spawn_worker_fn=spawn_worker_fn,
        )
        if result["status"] == "spawned":
            intent_queue.mark_done(intent["id"])
            results.append(result)
        elif result["status"] == "skipped" and result.get("reason") in (
            "escalated",
            "risk_latched",
        ):
            intent_queue.mark_cancelled(intent["id"], reason=result["reason"])
        # concurrency/lock: leave pending for next cycle
    return results
