#!/usr/bin/env python3
"""Promotion automation for the GitHub SDLC pipeline (workflow-outline §4.5, §5.3).

Subcommands:

- ``on-build --issue REF``  — propagate **In progress** to the parent story/spec
  when a task starts building (outline §5.3: parent goes In progress when any
  sub-issue builds). Run by /gh-build after ``prepare``.
- ``on-close --issue REF``  — react to a just-closed issue: when **all** of its
  parent's sub-issues are closed, open the parent-level PR (story → spec, or
  spec → main) and set the parent's Status to **Review / QA** (outline §4.5).
  Run by ``.github/workflows/promote.yml`` on every issue close.
- ``promote --issue REF``   — run the all-children-closed check directly on REF
  (manual invocation, e.g. after merging the final task PR by hand).

All results are reported as JSON on stdout. No-ops exit 0 with
``"action": "none"`` so the workflow never fails on unrelated issue closes.
Project Status updates degrade to warnings when the token lacks project scope.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

_BUILD_PUBLISH_PATH = _SCRIPT_DIR / "gh-build-publish.py"
_spec = importlib.util.spec_from_file_location("gh_build_publish", _BUILD_PUBLISH_PATH)
assert _spec and _spec.loader
_gbp = importlib.util.module_from_spec(_spec)
sys.modules["gh_build_publish"] = _gbp
_spec.loader.exec_module(_gbp)

gh_json = _gbp.gh_json
gh_run = _gbp.gh_run
graphql = _gbp.graphql
linked_branches = _gbp.linked_branches
default_branch = _gbp.default_branch
parse_repo = _gbp.parse_repo
parse_issue_spec = _gbp.parse_issue_spec
parse_development_branch = _gbp.parse_development_branch
resolve_project_for_task = _gbp.resolve_project_for_task
set_project_status = _gbp.set_project_status

ISSUE_WITH_PARENT_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      id
      number
      title
      state
      url
      parent {
        id
        number
        title
        state
        url
        repository { nameWithOwner }
        parent {
          id
          number
          title
          state
          url
          repository { nameWithOwner }
        }
      }
    }
  }
}
"""

SUB_ISSUE_STATES_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      subIssues(first: 100) {
        nodes { number title state url }
      }
    }
  }
}
"""

MAX_ANCESTOR_DEPTH = 3  # task → story → spec


def issue_node(repo: str, number: int) -> dict[str, Any] | None:
    owner, name = parse_repo(repo)
    data = graphql(
        ISSUE_WITH_PARENT_QUERY,
        {"owner": owner, "name": name, "number": int(number)},
    )
    return data.get("data", {}).get("repository", {}).get("issue")


def issue_repo(node: dict[str, Any], fallback_repo: str) -> str:
    return (node.get("repository") or {}).get("nameWithOwner") or fallback_repo


def sub_issue_states(repo: str, number: int) -> list[dict[str, Any]]:
    owner, name = parse_repo(repo)
    data = graphql(
        SUB_ISSUE_STATES_QUERY,
        {"owner": owner, "name": name, "number": int(number)},
    )
    issue = data.get("data", {}).get("repository", {}).get("issue") or {}
    return (issue.get("subIssues") or {}).get("nodes") or []


def branch_for_issue(repo: str, number: int) -> str | None:
    branches = linked_branches(repo, number)
    if len(branches) == 1:
        return next(iter(branches))
    if branches:
        return sorted(branches)[0]
    try:
        data = gh_json(["issue", "view", str(number), "--repo", repo, "--json", "body"])
    except subprocess.CalledProcessError:
        return None
    return parse_development_branch(data.get("body") or "")


def existing_open_pr(repo: str, head_branch: str) -> str | None:
    try:
        prs = gh_json(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--head",
                head_branch,
                "--state",
                "open",
                "--json",
                "url",
            ]
        )
    except subprocess.CalledProcessError:
        return None
    if prs:
        return prs[0].get("url")
    return None


def update_status(repo: str, issue_url: str, status_key: str) -> dict[str, Any]:
    project = resolve_project_for_task(issue_url, {}, repo)
    if not project:
        return {"ok": False, "warn": f"no project resolved for {issue_url}"}
    try:
        return set_project_status(project, issue_url, status_key)
    except subprocess.CalledProcessError as exc:
        return {"ok": False, "warn": f"status update failed: {exc.stderr or exc}"}


def promote_parent(parent: dict[str, Any], parent_repo: str) -> dict[str, Any]:
    """Open the parent-level PR and set Review / QA when all sub-issues are closed."""
    number = int(parent["number"])
    result: dict[str, Any] = {
        "action": "none",
        "parent": {"repo": parent_repo, "number": number, "url": parent.get("url")},
    }

    subs = sub_issue_states(parent_repo, number)
    if not subs:
        result["reason"] = "parent has no sub-issues"
        return result
    open_subs = [s for s in subs if (s.get("state") or "").upper() != "CLOSED"]
    if open_subs:
        result["reason"] = "open sub-issues remain"
        result["open_sub_issues"] = [s.get("url") for s in open_subs]
        return result

    branch = branch_for_issue(parent_repo, number)
    if not branch:
        result["reason"] = "no branch linked to parent issue"
        return result

    existing = existing_open_pr(parent_repo, branch)
    if existing:
        # PR already open (earlier fire, or a task PR when the parent is a task
        # whose bug sub-issues just closed) — nothing to promote.
        result["action"] = "pr-exists"
        result["pr"] = existing
        return result

    grandparent = parent.get("parent")
    if grandparent:
        gp_repo = issue_repo(grandparent, parent_repo)
        base = branch_for_issue(gp_repo, int(grandparent["number"]))
        level = "story"
    else:
        base = None
        level = "spec"
    if not base:
        base = default_branch(parent_repo)

    title = parent.get("title") or branch
    ref = f"{parent_repo}#{number}"
    if level == "story":
        body = (
            f"Closes {ref}\n\n"
            "All task sub-issues are closed — story PR opened automatically "
            "(workflow-outline §4.5). Review with the story-level cycle "
            "(2× /gh-review + /gh-resolve-issues), then **regular merge** "
            "(README §Merge strategy)."
        )
    else:
        body = (
            f"Part of {ref} — do **not** close the spec issue at merge; close it "
            "only after deployment is confirmed (README §Post-merge and release).\n\n"
            "All user-story sub-issues are closed — spec PR opened automatically "
            "(workflow-outline §4.5). Review with the spec-level cycle, then "
            "**squash merge** (README §Merge strategy)."
        )

    try:
        pr_url = gh_run(
            [
                "pr",
                "create",
                "--repo",
                parent_repo,
                "--base",
                base,
                "--head",
                branch,
                "--title",
                title,
                "--body",
                body,
            ]
        )
    except subprocess.CalledProcessError as exc:
        result["reason"] = f"pr create failed: {(exc.stderr or '').strip() or exc}"
        return result

    result["action"] = "promoted"
    result["level"] = level
    result["pr"] = pr_url
    result["base"] = base
    result["head"] = branch
    result["status_update"] = update_status(parent_repo, parent["url"], "review_qa")
    return result


def cmd_on_close(args: argparse.Namespace) -> int:
    repo, number = parse_issue_spec(args.issue)
    node = issue_node(repo, number)
    if not node:
        print(json.dumps({"action": "none", "reason": f"issue not found: {repo}#{number}"}))
        return 0
    parent = node.get("parent")
    if not parent:
        print(json.dumps({"action": "none", "reason": "closed issue has no parent"}))
        return 0
    result = promote_parent(parent, issue_repo(parent, repo))
    print(json.dumps(result, indent=2))
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    repo, number = parse_issue_spec(args.issue)
    node = issue_node(repo, number)
    if not node:
        print(json.dumps({"action": "none", "reason": f"issue not found: {repo}#{number}"}))
        return 0
    result = promote_parent(node, repo)
    print(json.dumps(result, indent=2))
    return 0


def cmd_on_build(args: argparse.Namespace) -> int:
    repo, number = parse_issue_spec(args.issue)
    node = issue_node(repo, number)
    ancestors: list[dict[str, Any]] = []
    depth = 0
    current, current_repo = node, repo
    while current and depth < MAX_ANCESTOR_DEPTH:
        parent = current.get("parent")
        if not parent:
            break
        parent_repo = issue_repo(parent, current_repo)
        entry = {
            "repo": parent_repo,
            "number": parent.get("number"),
            "url": parent.get("url"),
            "status_update": update_status(parent_repo, parent["url"], "in_progress"),
        }
        ancestors.append(entry)
        # The two-level parent query bottoms out here; re-fetch to walk higher.
        current = issue_node(parent_repo, int(parent["number"]))
        current_repo = parent_repo
        depth += 1
    print(json.dumps({"action": "on-build", "ancestors": ancestors}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    on_close = sub.add_parser(
        "on-close",
        help="Promote the closed issue's parent when all its sub-issues are closed",
    )
    on_close.add_argument("--issue", required=True, help="owner/repo#N or issue URL")
    on_close.set_defaults(func=cmd_on_close)

    promote = sub.add_parser(
        "promote",
        help="Run the all-children-closed promotion check directly on an issue",
    )
    promote.add_argument("--issue", required=True, help="owner/repo#N or issue URL")
    promote.set_defaults(func=cmd_promote)

    on_build = sub.add_parser(
        "on-build",
        help="Set ancestor story/spec issues to In progress when a task builds",
    )
    on_build.add_argument("--issue", required=True, help="owner/repo#N or issue URL")
    on_build.set_defaults(func=cmd_on_build)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
