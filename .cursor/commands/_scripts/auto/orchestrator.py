"""Phase 5 local goal orchestrator.

Usage:
  python3 orchestrator.py submit --goal "..." [--repo-root PATH]
  python3 orchestrator.py status [--repo-root PATH] [--goal-id ID]
  python3 orchestrator.py approve --spec-issue owner/repo#N [--repo-root PATH]

``submit`` publishes a Spec issue in To-do (no interactive /gh-spec review).
Human edits the Spec, then moves it To-do → In progress. The dispatcher
classifies that as ``goal_approve`` and calls ``handle_goal_approve``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from config import load_config, resolve_path
from domain_packs import list_packs, run_pack
from goal_store import GoalStore

def _repo_root_from_script() -> Path:
    return _SCRIPT_DIR.parents[3]


def local_decompose(goal: str) -> dict[str, Any]:
    """Deterministic Spec + story draft (no SDK). Human edits before approval."""
    title = goal.strip().splitlines()[0][:80] or "Untitled goal"
    if not title.lower().startswith("[auto]"):
        title = f"[auto] {title}"
    body = "\n".join(
        [
            "## Goal",
            "",
            goal.strip(),
            "",
            "## Acceptance Criteria",
            "",
            "- [ ] Human refined AC before moving Spec to In progress",
            "",
            "## Out of Scope",
            "",
            "- TBD",
            "",
            "## User Stories (proposed)",
            "",
            f"### US-01: Deliver {goal.strip()[:60]}",
            "",
            "As a user I want the goal implemented so that the outcome is delivered.",
            "",
            "### AC",
            "",
            "- [ ] Core behavior works",
            "",
        ]
    )
    stories = [
        {
            "id": "US-01",
            "title": f"US-01: Deliver {goal.strip()[:60]}",
            "body": (
                f"## Parent goal\n\n{goal.strip()}\n\n"
                "## Acceptance Criteria\n\n- [ ] Core behavior works\n"
            ),
        }
    ]
    return {"title": title, "body": body, "stories": stories}


def decompose_goal(goal: str, *, decompose_fn: Callable[[str], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Produce Spec title/body/stories. Prefer injected fn, then SDK, then local."""
    if decompose_fn is not None:
        return decompose_fn(goal)
    try:
        return _sdk_decompose(goal)
    except Exception:  # noqa: BLE001 - SDK optional; fall back to local draft
        return local_decompose(goal)


def _sdk_decompose(goal: str) -> dict[str, Any]:
    """Best-effort Cursor SDK decomposition. Raises if SDK unavailable."""
    try:
        from cursor_sdk import Agent  # type: ignore
    except ImportError as exc:
        raise RuntimeError("cursor-sdk not installed") from exc

    # Public beta surface varies; keep a narrow contract and parse JSON from the reply.
    prompt = (
        "Decompose this goal into a GitHub Spec issue draft. "
        "Return ONLY JSON with keys title, body, stories "
        "(stories is a list of {id, title, body}). "
        f"Goal:\n{goal}"
    )
    agent = Agent.create(model="auto", local=True)  # type: ignore[attr-defined]
    result = agent.prompt(prompt)
    text = result if isinstance(result, str) else getattr(result, "text", str(result))
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise RuntimeError("SDK decompose returned no JSON")
    data = json.loads(match.group(0))
    if not isinstance(data, dict) or "title" not in data or "body" not in data:
        raise RuntimeError("SDK decompose JSON missing title/body")
    data.setdefault("stories", [])
    return data


def create_spec_issue(
    *,
    repo: str,
    title: str,
    body: str,
    run_fn: Callable[..., subprocess.CompletedProcess] | None = None,
) -> dict[str, Any]:
    """Create a Spec-typed GitHub issue. Returns {number, url, issue}."""
    run = run_fn or subprocess.run
    cmd = [
        "gh",
        "issue",
        "create",
        "--repo",
        repo,
        "--title",
        title,
        "--body",
        body,
        "--json",
        "number,url",
    ]
    # Prefer issue type when the repo supports it (ignore failure).
    typed = run(
        [
            "gh",
            "issue",
            "create",
            "--repo",
            repo,
            "--title",
            title,
            "--body",
            body,
            "--type",
            "Spec",
            "--json",
            "number,url",
        ],
        capture_output=True,
        text=True,
    )
    if typed.returncode != 0:
        typed = run(cmd, capture_output=True, text=True)
    if typed.returncode != 0:
        raise RuntimeError(f"gh issue create failed: {typed.stderr or typed.stdout}")
    payload = json.loads(typed.stdout)
    number = int(payload["number"])
    url = payload["url"]
    return {"number": number, "url": url, "issue": f"{repo}#{number}"}


def add_issue_to_project_todo(
    *,
    owner: str,
    project_number: int,
    issue_url: str,
    set_status_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Add issue to the Project board and set Status To-do when possible."""
    if set_status_fn is not None:
        return set_status_fn(
            owner=owner,
            project_number=project_number,
            issue_url=issue_url,
            status="todo",
        )
    # Best-effort via gh project commands; failure is non-fatal for submit.
    try:
        subprocess.run(
            [
                "gh",
                "project",
                "item-add",
                str(project_number),
                "--owner",
                owner,
                "--url",
                issue_url,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        pass
    return {"ok": True, "warn": "status may need manual To-do set"}


def create_story_issue(
    *,
    repo: str,
    title: str,
    body: str,
    parent_number: int,
    run_fn: Callable[..., subprocess.CompletedProcess] | None = None,
) -> dict[str, Any]:
    run = run_fn or subprocess.run
    full_body = body.rstrip() + f"\n\nParent: {repo}#{parent_number}\n"
    result = run(
        [
            "gh",
            "issue",
            "create",
            "--repo",
            repo,
            "--title",
            title,
            "--body",
            full_body,
            "--type",
            "User Story",
            "--json",
            "number,url",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        result = run(
            [
                "gh",
                "issue",
                "create",
                "--repo",
                repo,
                "--title",
                title,
                "--body",
                full_body,
                "--json",
                "number,url",
            ],
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        raise RuntimeError(f"gh issue create story failed: {result.stderr or result.stdout}")
    payload = json.loads(result.stdout)
    number = int(payload["number"])
    # Link as sub-issue when supported.
    run(
        [
            "gh",
            "issue",
            "develop",
            str(parent_number),
            "--repo",
            repo,
            "--name",
            f"story-link-{number}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    # Sub-issue API via gh may vary; also try GraphQL-less parent comment.
    run(
        [
            "gh",
            "issue",
            "comment",
            str(parent_number),
            "--repo",
            repo,
            "--body",
            f"Created User Story {repo}#{number}: {payload['url']}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return {"number": number, "url": payload["url"], "issue": f"{repo}#{number}"}


def submit_goal(
    cfg: dict[str, Any],
    goal: str,
    *,
    decompose_fn: Callable[[str], dict[str, Any]] | None = None,
    create_spec_fn: Callable[..., dict[str, Any]] | None = None,
    add_to_project_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Decompose goal, publish Spec in To-do, persist awaiting_approval goal."""
    draft = decompose_goal(goal, decompose_fn=decompose_fn)
    create = create_spec_fn or create_spec_issue
    spec = create(repo=cfg["repo"], title=draft["title"], body=draft["body"])
    add = add_to_project_fn or add_issue_to_project_todo
    add(
        owner=cfg["project"]["owner"],
        project_number=int(cfg["project"]["number"]),
        issue_url=spec["url"],
    )
    state_dir = resolve_path(Path(cfg["_repo_root"]), cfg["state_dir"])
    store = GoalStore(state_dir)
    record = store.create(
        goal_text=goal,
        spec_issue=spec["issue"],
        spec_url=spec["url"],
        title=draft["title"],
        stories=list(draft.get("stories") or []),
    )
    return {"goal": record, "spec": spec, "draft": draft}


def handle_goal_approve(
    cfg: dict[str, Any],
    *,
    spec_issue: str,
    create_story_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create User Stories from the goal draft and mark the goal running."""
    state_dir = resolve_path(Path(cfg["_repo_root"]), cfg["state_dir"])
    store = GoalStore(state_dir)
    record = store.get_by_spec(spec_issue)
    if record is None:
        return {"status": "skipped", "reason": "no_goal_for_spec", "spec_issue": spec_issue}
    if record.get("status") != "awaiting_approval":
        return {
            "status": "skipped",
            "reason": f"goal_status_{record.get('status')}",
            "goal": record,
        }

    repo = cfg["repo"]
    parent_number = int(spec_issue.split("#")[-1])
    create = create_story_fn or create_story_issue
    story_issues: list[dict[str, Any]] = []
    for story in record.get("stories") or []:
        created = create(
            repo=repo,
            title=story.get("title") or story.get("id") or "User Story",
            body=story.get("body") or "",
            parent_number=parent_number,
        )
        story_issues.append(created)

    record["story_issues"] = story_issues
    record["status"] = "running"
    store.write(record)
    return {"status": "approved", "goal": record, "story_issues": story_issues}


def enrich_transitions_with_goals(
    transitions: list[dict[str, Any]],
    store: GoalStore,
) -> list[dict[str, Any]]:
    """Attach goal_id/has_goal onto Spec transitions for classify_transition."""
    enriched: list[dict[str, Any]] = []
    for transition in transitions:
        t = dict(transition)
        if t.get("issue_type") == "Spec":
            goal = store.get_by_spec(t["issue"])
            if goal:
                t["has_goal"] = True
                t["goal_id"] = goal["id"]
        enriched.append(t)
    return enriched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    submit_p = sub.add_parser("submit", help="Publish Spec in To-do for a goal")
    submit_p.add_argument("--goal", required=True)
    submit_p.add_argument("--repo-root", default=None)

    status_p = sub.add_parser("status", help="Show goal(s)")
    status_p.add_argument("--goal-id", default=None)
    status_p.add_argument("--repo-root", default=None)

    approve_p = sub.add_parser("approve", help="Manually run goal approval for a Spec")
    approve_p.add_argument("--spec-issue", required=True)
    approve_p.add_argument("--repo-root", default=None)

    pack_p = sub.add_parser("pack", help="Run a domain pack")
    pack_p.add_argument("name", help="Pack name or 'list'")
    pack_p.add_argument("--repo-root", default=None)

    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root) if getattr(args, "repo_root", None) else _repo_root_from_script()
    cfg = load_config(repo_root)

    if args.command == "submit":
        result = submit_goal(cfg, args.goal)
        print(json.dumps(result, indent=2, default=str))
        return 0

    if args.command == "status":
        store = GoalStore(resolve_path(repo_root, cfg["state_dir"]))
        if args.goal_id:
            print(json.dumps(store.get(args.goal_id), indent=2, default=str))
        else:
            print(json.dumps(store.list_goals(), indent=2, default=str))
        return 0

    if args.command == "approve":
        result = handle_goal_approve(cfg, spec_issue=args.spec_issue)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("status") == "approved" else 1

    if args.command == "pack":
        if args.name == "list":
            print(json.dumps({"packs": list_packs()}, indent=2))
            return 0
        result = run_pack(args.name, cfg)
        print(
            json.dumps(
                {k: v for k, v in result.items() if k != "job_record"},
                indent=2,
                default=str,
            )
        )
        return 0 if result.get("status") != "spawn_error" else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
