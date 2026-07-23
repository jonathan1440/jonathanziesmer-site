"""Entry point: `python3 .cursor/commands/_scripts/auto/dispatch.py once|poll`.

One dispatch cycle:
  1. reap finished/stale jobs; retry (up to `retry_budget`) or escalate failures;
     record chain failures for failed chain-kicked builds
  2. fetch project items -> diff against the saved status snapshot
  3. fetch merged PRs -> diff against the saved merged-PR snapshot
  4. for each newly merged task PR, try to kick the next unblocked sibling Task
  5. build post_merge actionables for newly merged spec PRs
  6. clear escalation latches for issues that transitioned
  7. filter everything through concurrency/lock/escalation gates and spawn
  8. persist the status snapshot (with chain kicks reflected) and merged-PR snapshot
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import chain
import diff
import escalate
import filter as dispatch_filter
import prompts
import prs
import runner
from admission import admit_and_spawn, drain_queue
from config import load_config, resolve_path
from fetch import fetch_project_items
from goal_store import GoalStore
from intent_queue import IntentQueue
from log import RunLog, run_finished_record
from memory import MemoryStore
from orchestrator import enrich_transitions_with_goals, handle_goal_approve
from registry import Registry
from spawn_headless import spawn_headless
from spawn_worker import spawn_worker


def _finalize_maintenance_memory(job: dict[str, Any], *, status: str, registry) -> None:
    """Release or fail a maintenance claim when a spawned maintenance job ends.

    Successful agent runs release the claim without writing a known-good receipt.
    Re-fire is gated by ``last_run`` intervals plus GitHub open-PR / marker
    dedupe in the probes — a receipt here would permanently suppress retries
    when the agent exited without opening a PR.
    """
    fingerprint = job.get("fingerprint")
    task = job.get("maintenance_task")
    if not fingerprint or not task:
        return
    try:
        memory = MemoryStore(registry.state_dir)
        if status in ("completed", "done", "success"):
            memory.release_claim(task, fingerprint)
        else:
            memory.fail(
                task,
                fingerprint,
                error=f"job {job.get('id')} ended {status}",
                metadata={"job_id": job.get("id")},
            )
    except Exception:  # noqa: BLE001 - memory cleanup must not break dispatch
        pass


def _repo_root_from_script() -> Path:
    # .cursor/commands/_scripts/auto/dispatch.py -> repo root is 4 parents up.
    return _SCRIPT_DIR.parents[3]


def _resolve_spec_item(event: dict[str, Any], items: dict[str, Any]) -> dict[str, Any] | None:
    for ref in event.get("closing_issues", []):
        item = items.get(ref)
        if item and item.get("issue_type") == "Spec":
            return item
    return None


def _retry_transition_for_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "issue": job.get("issue"),
        "url": job.get("url"),
        "number": job.get("number"),
        "repo": job.get("repo"),
        "title": job.get("title"),
        "parent_number": job.get("parent_number"),
        "pr": job.get("pr"),
    }


def _handle_reaped_job(
    job: dict[str, Any],
    *,
    cfg: dict[str, Any],
    registry,
    run_log: RunLog,
    workspace: Path | str,
    log_dir: Path | str,
    spawn_headless_fn,
    spawn_worker_fn,
    escalate_fn,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Retry or escalate a reaped job. Returns (spawned_job, skipped_job).

    ``Registry.reap()`` has already finalized the job status; this emits
    lifecycle ``run_finished`` and decides retry vs escalate.
    """
    status = job.get("status") or "completed"
    outcome_known = not (status == "timeout" and job.get("mode") == "worker")
    run_log.write(
        run_finished_record(
            job,
            status=status,
            exit_code=job.get("exit_code"),
            duration_seconds=runner.duration_seconds_for(job),
            outcome_known=outcome_known,
        )
    )

    if status not in ("failed", "timeout"):
        _finalize_maintenance_memory(job, status=status, registry=registry)
        run_log.write({"event": "reap", "job_id": job.get("id"), "status": status})
        return None, None

    if job.get("kind") == "build" and job.get("chain_kicked"):
        parent_key = job.get("parent_key")
        if parent_key:
            chain.record_chain_failure(registry, parent_key)

    run_log.write({"event": "reap_failed", "job_id": job.get("id"), "status": status})

    retry_budget = cfg.get("retry_budget", 1)
    can_retry = (
        job.get("attempts", 1) <= retry_budget
        and job.get("prompt_class")
        and (job.get("url") or str(job.get("kind", "")).startswith("maintenance"))
    )
    if can_retry:
        attempts = registry.bump_attempt(job)
        prompt = prompts.build_prompt(job["prompt_class"], _retry_transition_for_job(job))
        runner.spawn_for_job(
            job,
            prompt,
            cfg,
            workspace,
            log_dir,
            spawn_headless_fn=spawn_headless_fn,
            spawn_worker_fn=spawn_worker_fn,
            run_log=run_log,
        )
        registry.write_job(job)
        run_log.write({"event": "retry_spawn", "job_id": job["id"], "attempts": attempts})
        return job, None

    _finalize_maintenance_memory(job, status=status, registry=registry)
    if job.get("issue"):
        registry.mark_escalated(job.get("issue"))
        escalate_fn(
            job.get("issue"),
            reason=(
                f"Auto-workflow {job.get('kind')} job failed after "
                f"{job.get('attempts', 1)} attempt(s); exceeded retry_budget={retry_budget}."
            ),
            owner_mention=cfg.get("escalate_owner") or "",
        )
    run_log.write({"event": "escalated", "job_id": job.get("id"), "issue": job.get("issue")})
    return None, job


def dispatch_once(
    cfg: dict[str, Any] | None = None,
    *,
    repo_root: Path | str | None = None,
    fetch_fn=fetch_project_items,
    fetch_merged_prs_fn=None,
    kick_next_fn=None,
    spawn_headless_fn=spawn_headless,
    spawn_worker_fn=spawn_worker,
    escalate_fn=None,
) -> dict[str, Any]:
    if cfg is None:
        cfg = load_config(repo_root or _repo_root_from_script())
    fetch_merged_prs_fn = fetch_merged_prs_fn or prs.fetch_merged_prs
    kick_next_fn = kick_next_fn or chain.kick_next
    escalate_fn = escalate_fn or escalate.escalate_issue

    root = Path(cfg["_repo_root"])
    state_dir = resolve_path(root, cfg["state_dir"])
    log_dir = resolve_path(root, cfg["log_dir"])
    workspace = resolve_path(root, cfg.get("workspace") or ".")

    registry = Registry(state_dir)
    run_log = RunLog(log_dir)
    intent_queue = IntentQueue(state_dir)

    reaped = registry.reap()
    spawned: list[dict[str, Any]] = []
    skipped_or_ignored: list[dict[str, Any]] = []
    queued: list[dict[str, Any]] = []

    for job in reaped:
        if not job:
            continue
        retried, escalated = _handle_reaped_job(
            job,
            cfg=cfg,
            registry=registry,
            run_log=run_log,
            workspace=workspace,
            log_dir=log_dir,
            spawn_headless_fn=spawn_headless_fn,
            spawn_worker_fn=spawn_worker_fn,
            escalate_fn=escalate_fn,
        )
        if retried is not None:
            spawned.append(retried)
        if escalated is not None:
            skipped_or_ignored.append(escalated)

    # Drain durable intents before admitting new board transitions.
    for result in drain_queue(
        cfg=cfg,
        registry=registry,
        run_log=run_log,
        workspace=workspace,
        log_dir=log_dir,
        intent_queue=intent_queue,
        spawn_headless_fn=spawn_headless_fn,
        spawn_worker_fn=spawn_worker_fn,
    ):
        if result.get("job"):
            spawned.append(result["job"])

    owner = cfg["project"]["owner"]
    number = cfg["project"]["number"]
    items_list = fetch_fn(owner, number)
    items_by_key = {it["issue"]: it for it in items_list}

    previous_snapshot = registry.load_snapshot()
    current_snapshot = diff.snapshot_from_items(items_list)
    status_transitions = diff.diff_snapshots(previous_snapshot, current_snapshot)

    goal_store = GoalStore(state_dir)
    status_transitions = enrich_transitions_with_goals(status_transitions, goal_store)

    for transition in status_transitions:
        if registry.is_escalated(transition["issue"]):
            registry.clear_escalated(transition["issue"])

    merged_keys = set(registry.load_merged_prs())
    merge_events = fetch_merged_prs_fn(
        cfg["repo"], lookback_hours=cfg.get("merged_pr_lookback_hours", 72)
    )
    new_events = prs.diff_merged_prs(merged_keys, merge_events)

    synthetic_transitions: list[dict[str, Any]] = []
    handled_keys = set(merged_keys)
    post_merge_events: list[dict[str, Any]] = []
    project = {"owner": owner, "number": number}

    for event in new_events:
        run_log.write({"event": "merge_seen", "kind": event.get("kind"), "pr": event.get("pr")})
        key = prs.pr_key(event["repo"], event["number"])

        if event["kind"] == "task_pr_merged":
            result = kick_next_fn(event, cfg=cfg, registry=registry, items=items_by_key, project=project)
            action = result.get("action")
            if action == "kick":
                synthetic_transitions.append(result["transition"])
                handled_keys.add(key)
                run_log.write(
                    {
                        "event": "chain_kick",
                        "pr": event.get("pr"),
                        "issue": result["transition"]["issue"],
                    }
                )
            elif action == "locked":
                run_log.write(
                    {"event": "chain_locked", "pr": event.get("pr"), "lock_key": result.get("lock_key")}
                )
                # Do not mark handled: retry once the lock frees up.
            else:
                handled_keys.add(key)
                run_log.write({"event": f"chain_{action}", "pr": event.get("pr")})
            continue

        # spec_pr_merged
        spec_item = _resolve_spec_item(event, items_by_key)
        if spec_item:
            post_merge_events.append(
                {
                    "kind": "spec_pr_merged",
                    "issue": spec_item["issue"],
                    "repo": spec_item["repo"],
                    "number": spec_item["number"],
                    "url": spec_item.get("url"),
                    "title": spec_item.get("title"),
                    "pr": event["number"],
                    "merged_at": event["merged_at"],
                }
            )
        handled_keys.add(key)

    actionable = dispatch_filter.filter_transitions(
        status_transitions + synthetic_transitions,
        registry=registry,
        concurrency=cfg["concurrency"],
        enqueue_on_cap=False,  # admission handles queueing
    )
    reserved = len(actionable)
    actionable.extend(
        dispatch_filter.filter_post_merge_events(
            post_merge_events,
            registry=registry,
            concurrency=cfg["concurrency"],
            reserved=reserved,
            enqueue_on_cap=False,
        )
    )

    chain_kicked_issue_keys = {t["issue"] for t in synthetic_transitions}

    for entry in actionable:
        transition = entry["transition"]
        kind = entry["kind"]

        # Mechanical goal approval runs in-process (creates stories); no agent spawn.
        if kind == "goal_approve":
            approve_result = handle_goal_approve(cfg, spec_issue=transition["issue"])
            run_log.write(
                {
                    "event": "goal_approve",
                    "issue": transition["issue"],
                    "result": approve_result.get("status"),
                    "story_count": len(approve_result.get("story_issues") or []),
                }
            )
            continue

        job_extras: dict[str, Any] = {}
        if kind == "build" and transition["issue"] in chain_kicked_issue_keys:
            job_extras["chain_kicked"] = True
            job_extras["parent_key"] = (
                f"{transition['repo']}+parent#{transition.get('parent_number')}"
            )

        result = admit_and_spawn(
            cfg=cfg,
            registry=registry,
            run_log=run_log,
            workspace=workspace,
            log_dir=log_dir,
            kind=kind,
            prompt_class=entry["prompt_class"],
            transition=transition,
            lock_key=entry["lock_key"],
            intent_queue=intent_queue,
            job_extras=job_extras or None,
            spawn_headless_fn=spawn_headless_fn,
            spawn_worker_fn=spawn_worker_fn,
        )
        if result["status"] == "spawned" and result.get("job"):
            spawned.append(result["job"])
        elif result["status"] == "queued":
            queued.append(result.get("intent") or {})
        else:
            if result.get("job"):
                skipped_or_ignored.append(result["job"])

    for transition in synthetic_transitions:
        entry = current_snapshot.setdefault(
            transition["issue"],
            {
                "repo": transition["repo"],
                "number": transition["number"],
                "url": transition.get("url"),
                "title": transition.get("title"),
                "issue_type": transition.get("issue_type"),
                "parent_number": transition.get("parent_number"),
                "task_sub_issue_count": transition.get("task_sub_issue_count"),
            },
        )
        entry["status"] = "in_progress"

    registry.save_snapshot(current_snapshot)
    registry.save_merged_prs(handled_keys)

    return {
        "items": items_list,
        "transitions": status_transitions,
        "spawned": spawned,
        "queued": queued,
        "skipped_or_ignored": skipped_or_ignored,
        "reaped": reaped,
        "jobs": [job["id"] for job in spawned],
    }


def poll_loop(
    cfg: dict[str, Any] | None = None,
    *,
    repo_root: Path | str | None = None,
    iterations: int | None = None,
) -> None:
    if cfg is None:
        cfg = load_config(repo_root or _repo_root_from_script())
    count = 0
    while iterations is None or count < iterations:
        dispatch_once(cfg)
        count += 1
        if iterations is not None and count >= iterations:
            break
        time.sleep(cfg["poll_interval_seconds"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["once", "poll"])
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else _repo_root_from_script()
    cfg = load_config(repo_root)

    if args.mode == "once":
        result = dispatch_once(cfg)
        print(
            f"transitions={len(result['transitions'])} spawned={len(result['spawned'])} "
            f"skipped={len(result['skipped_or_ignored'])} reaped={len(result['reaped'])}"
        )
    else:
        poll_loop(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
