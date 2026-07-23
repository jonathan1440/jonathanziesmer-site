#!/usr/bin/env python3
"""
GitHub bug resolution automation for /gh-resolve-issues.

Usage:
  gh-resolve-publish.py preflight
  gh-resolve-publish.py context --issue OWNER/REPO#N | URL [--pr URL] [--finding-kind bug|task] [-o PATH]
  gh-resolve-publish.py start --issue REF [--pr URL] [--finding-kind bug|task] [-o PATH]
  gh-resolve-publish.py checkout-task --input CONTEXT.json [--repo-path PATH] [-o PATH]
  gh-resolve-publish.py create-bug-branch --input CONTEXT.json --bug RR-01 [-o PATH]
  gh-resolve-publish.py commit-push --input CONTEXT.json --bug RR-01 [--message MSG] [-o PATH]
  gh-resolve-publish.py merge-bugs --input CONTEXT.json [-o PATH]
  gh-resolve-publish.py gates --input CONTEXT.json [--require-verify] [--verify-result PATH] [-o PATH]
  gh-resolve-publish.py verify --input CONTEXT.json [--repo-path PATH] [-o PATH]
  gh-resolve-publish.py update-pr --input CONTEXT.json [-o PATH]
  gh-resolve-publish.py close-bugs --input CONTEXT.json [--allow-partial] [-o PATH]
  gh-resolve-publish.py record-bug --input CONTEXT.json --bug RR-01 --commit SHA [--test-file PATH ...] [-o PATH]
  gh-resolve-publish.py finish --input CONTEXT.json [--require-verify] [--verify-result PATH] [-o PATH]
  gh-resolve-publish.py check-merge-allowed --issue-type Bug|Task|Spec|User Story [--finding] [--branch NAME]
  gh-resolve-publish.py merge-finding-pr --repo OWNER/REPO --pr N --issue-type Bug|Task [--finding] [--branch NAME]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_SPEC_PUBLISH_PATH = _SCRIPT_DIR / "gh-spec-publish.py"
_BUILD_PUBLISH_PATH = _SCRIPT_DIR / "gh-build-publish.py"
_REVIEW_PUBLISH_PATH = _SCRIPT_DIR / "gh-review-publish.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_gsp = _load_module("gh_spec_publish", _SPEC_PUBLISH_PATH)
_build = _load_module("gh_build_publish", _BUILD_PUBLISH_PATH)
_review = _load_module("gh_review_publish", _REVIEW_PUBLISH_PATH)

build_context = _build.build_context
check_blockers = _build.check_blockers
extract_ac_scenarios = _build.extract_ac_scenarios
find_local_repo_path = _build.find_local_repo_path
find_manifest_path = _build.find_manifest_path
git_run = _build.git_run
run_verify = _build.run_verify
parse_issue_spec = _build.parse_issue_spec
parse_spec_path = _build.parse_spec_path
resolve_parent_branch = _build.resolve_parent_branch
resolve_project_for_task = _build.resolve_project_for_task
set_project_status = _build.set_project_status
workspace_roots_from_args = _build.workspace_roots_from_args
write_json = _build.write_json
load_json = _build.load_json
issue_graph = _review.issue_graph
list_linked_prs = _review.list_linked_prs
find_open_pr_by_head = _review.find_open_pr_by_head
find_pr_by_issue_ref_in_body = _review.find_pr_by_issue_ref_in_body
list_issue_develop_branches = _review.list_issue_develop_branches
is_rr_sub_issue = _review.is_rr_sub_issue
extract_rr_id = _review.extract_rr_id
close_issue = _review.close_issue
parse_repos_touched = _review.parse_repos_touched
gh_json = _gsp.gh_json
gh_run = _gsp.gh_run
load_manifest = _gsp.load_manifest
slugify_story_title = _gsp.slugify_story_title

STORY_TITLE_ID_PATTERN = re.compile(r"^(US-\d+)", re.IGNORECASE)
STORY_AC_HEADING_PATTERN = re.compile(
    r"^###\s+(AC-\d+)\s*[—\-]",
    re.IGNORECASE | re.MULTILINE,
)
DEFAULT_STORY_VERIFY_CMD = "pytest -q"
FINDING_KINDS = ("bug", "task")


def normalize_finding_kind(kind: str | None) -> str:
    normalized = (kind or "bug").strip().lower()
    if normalized not in FINDING_KINDS:
        allowed = ", ".join(FINDING_KINDS)
        raise SystemExit(f"invalid finding kind {kind!r}; expected one of: {allowed}")
    return normalized


def finding_kind_label(kind: str) -> str:
    normalized = normalize_finding_kind(kind)
    return "Task" if normalized == "task" else "Bug"


def is_finding_sub_issue(node: dict[str, Any], finding_kind: str) -> bool:
    return is_rr_sub_issue(node, kind=normalize_finding_kind(finding_kind))

BACKTICK_PATH_PATTERN = re.compile(r"`([^`]+)`")
VERIFY_PATTERN = re.compile(r"Verify:\s*`([^`]+)`", re.IGNORECASE)
TEST_FILE_PATTERN = re.compile(
    r"(?:Add/update|Test file|Tests?):\s*`([^`]+)`",
    re.IGNORECASE,
)
BUG_BRANCH_PREFIX = "bug/"
PR_URL_PATTERN = re.compile(
    r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)",
    re.IGNORECASE,
)


def section_text(body: str, heading: str) -> str:
    pattern = re.compile(rf"^{re.escape(heading)}\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(body)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^##\s+", body[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(body)
    return body[start:end].strip()


def parse_involved_code_paths(body: str) -> list[str]:
    text = section_text(body, "## Involved code")
    files: list[str] = []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        if re.match(r"^\|\s*-+", line):
            continue
        if "path" in line.lower() and "role" in line.lower():
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        path = cells[0].strip("` ")
        if path and path.lower() != "path" and not path.startswith("-"):
            files.append(path)
    return files


def parse_bug_tests(body: str) -> dict[str, Any]:
    text = section_text(body, "## Tests")
    if not text:
        return {"verify_cmd": "", "test_files": []}
    verify_match = VERIFY_PATTERN.search(text)
    verify_cmd = verify_match.group(1).strip() if verify_match else ""
    test_files: list[str] = []
    for match in TEST_FILE_PATTERN.finditer(text):
        test_files.append(match.group(1).strip())
    for line in text.splitlines():
        for match in BACKTICK_PATH_PATTERN.finditer(line):
            path = match.group(1).strip()
            if path.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".rb")):
                if path not in test_files:
                    test_files.append(path)
    return {"verify_cmd": verify_cmd, "test_files": test_files}


def parse_bug_summary(body: str, title: str) -> str:
    summary_match = re.search(r"\*\*Summary:\*\*\s*(.+)$", body, re.MULTILINE)
    if summary_match:
        return summary_match.group(1).strip()
    title_match = re.match(r"^\[[^\]]+\]\s*(.+)$", title.strip())
    if title_match:
        return title_match.group(1).strip()
    return title.strip()


def proposed_bug_branch(finding_id: str, summary: str) -> str:
    slug = slugify_story_title(summary, max_len=48)
    return f"{BUG_BRANCH_PREFIX}{finding_id.lower()}-{slug}"


def fetch_issue_data(repo: str, number: int) -> dict[str, Any]:
    return gh_json(
        [
            "issue",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "number,title,body,state,url",
        ]
    )


def is_story_issue(body: str, title: str) -> bool:
    """True when the issue is a user story (not a task with ## Traceability)."""
    if section_text(body, "## Traceability"):
        return False
    if section_text(body, "## User story"):
        return True
    if section_text(body, "## Acceptance scenarios"):
        return True
    return bool(STORY_TITLE_ID_PATTERN.match(title.strip()))


def parse_story_id_from_title(title: str) -> str | None:
    match = STORY_TITLE_ID_PATTERN.match(title.strip())
    return match.group(1).upper() if match else None


def parse_story_ac_ids(body: str) -> list[str]:
    return [
        match.group(1).upper()
        for match in STORY_AC_HEADING_PATTERN.finditer(body)
    ]


def build_story_context(
    story_repo: str,
    story_number: int,
    roots: list[Path],
    data: dict[str, Any],
) -> dict[str, Any]:
    body = data.get("body") or ""
    title = data.get("title") or ""
    story_id = parse_story_id_from_title(title)
    if not story_id:
        raise SystemExit(
            f"story issue {story_repo}#{story_number} missing US-XX id in title"
        )

    repos_touched = parse_repos_touched(body)
    repository = repos_touched[0] if repos_touched else story_repo
    local_repo_path = find_local_repo_path(repository, roots)
    spec_path = parse_spec_path(body)
    manifest_path = find_manifest_path(spec_path, local_repo_path)
    manifest = load_manifest(manifest_path) if manifest_path else {}

    ac_ids = parse_story_ac_ids(body)
    ac_scenarios = extract_ac_scenarios(body, ac_ids)
    branch_info = resolve_parent_branch(
        repository,
        story_repo,
        story_number,
        story_id,
        manifest,
    )
    task_branch_info = {
        "branch": branch_info.get("branch"),
        "source": branch_info.get("source", "none"),
        "exists_on_remote": branch_info.get("exists_on_remote", False),
    }
    if not task_branch_info["branch"]:
        for branch in list_issue_develop_branches(story_repo, story_number):
            if branch.startswith("user-story/"):
                task_branch_info = {
                    "branch": branch,
                    "source": "linked",
                    "exists_on_remote": True,
                }
                break

    project = resolve_project_for_task(data["url"], manifest, story_repo)
    issue_ref = {
        "repo": story_repo,
        "number": story_number,
        "title": title,
        "url": data.get("url"),
        "state": data.get("state"),
    }

    return {
        "issue_kind": "story",
        "task_issue": issue_ref,
        "story_issue": {
            "repo": story_repo,
            "number": story_number,
            "id": story_id,
            "title": title,
            "url": data.get("url"),
            "state": data.get("state"),
        },
        "repository": repository,
        "local_repo_path": local_repo_path,
        "manifest_path": str(manifest_path) if manifest_path else None,
        "spec_path": spec_path,
        "task_summary": section_text(body, "## User story"),
        "scope_files": [],
        "test_files": [],
        "verify_cmd": DEFAULT_STORY_VERIFY_CMD,
        "patterns": [],
        "ac_ids": ac_ids,
        "ac_scenarios": ac_scenarios,
        "blockers": [],
        "blocker_gate": check_blockers([]),
        "task_branch": task_branch_info,
        "parent_branch": branch_info,
        "project": project,
        "work_issue_id": None,
    }


def scope_files_from_bugs(bugs: list[dict[str, Any]]) -> list[str]:
    combined: list[str] = []
    for bug in bugs:
        combined.extend(bug.get("scope_files") or [])
    return list(dict.fromkeys(combined))


def resolve_issue_kind_label(ctx: dict[str, Any]) -> str:
    return "story" if ctx.get("issue_kind") == "story" else "task"


def parse_bug_issue(node: dict[str, Any], task_ctx: dict[str, Any]) -> dict[str, Any]:
    body = node.get("body") or ""
    title = node.get("title") or ""
    finding_id = extract_rr_id(title, body)
    if not finding_id:
        raise SystemExit(f"bug sub-issue missing finding id: {title!r}")
    summary = parse_bug_summary(body, title)
    involved = parse_involved_code_paths(body)
    tests = parse_bug_tests(body)
    task_scope = list(task_ctx.get("scope_files") or [])
    scope_files = involved if involved else task_scope
    verify_cmd = tests["verify_cmd"] or task_ctx.get("verify_cmd") or ""
    return {
        "finding_id": finding_id,
        "repo": node.get("repo") or node.get("repository", {}).get("nameWithOwner"),
        "number": node.get("number"),
        "title": title,
        "url": node.get("url"),
        "state": node.get("state"),
        "summary": summary,
        "scope_files": scope_files,
        "involved_files": involved,
        "test_files": tests["test_files"],
        "verify_cmd": verify_cmd,
        "reproduction": section_text(body, "## Reproduction"),
        "recommendation": section_text(body, "## Recommendation"),
        "proposed_branch": proposed_bug_branch(finding_id, summary),
        "branch": None,
        "commit": None,
        "status": "open",
    }


def select_linked_pr(
    linked_prs: list[dict[str, Any]],
    task_repo: str,
    task_branch: str | None,
) -> dict[str, Any] | None:
    open_prs = [pr for pr in linked_prs if pr.get("state") == "OPEN"]
    if not open_prs:
        return None
    if task_branch:
        for pr in open_prs:
            if pr.get("head_ref") == task_branch and pr.get("repo") == task_repo:
                return pr
    for pr in open_prs:
        if pr.get("repo") == task_repo:
            return pr
    return open_prs[0]


def parse_pr_url(url: str) -> dict[str, Any]:
    match = PR_URL_PATTERN.search(url.strip())
    if not match:
        raise SystemExit(f"invalid PR URL: {url!r}")
    repo = f"{match.group('owner')}/{match.group('repo')}"
    number = int(match.group("number"))
    return {
        "repo": repo,
        "number": number,
        "url": f"https://github.com/{repo}/pull/{number}",
        "state": "OPEN",
    }


def apply_pr_override(ctx: dict[str, Any], pr_url: str | None) -> None:
    if not pr_url:
        return
    override = parse_pr_url(pr_url)
    ctx["linked_pr_override"] = override
    ctx["linked_pr"] = override


def resolve_linked_pr(ctx: dict[str, Any]) -> dict[str, Any] | None:
    override = ctx.get("linked_pr_override")
    if override:
        return override

    task = ctx["task_issue"]
    task_repo = task["repo"]
    task_number = int(task["number"])
    task_branch = ctx.get("task_branch", {}).get("branch")
    code_repo = ctx.get("repository") or task_repo

    linked_prs = ctx.get("linked_prs") or list_linked_prs(task_repo, task_number)
    selected = select_linked_pr(linked_prs, task_repo, task_branch)
    if selected:
        return selected

    if task_branch and code_repo:
        by_head = find_open_pr_by_head(code_repo, task_branch)
        if by_head:
            return by_head

    if code_repo:
        by_body = find_pr_by_issue_ref_in_body(
            code_repo, task_number, task_branch=task_branch
        )
        if by_body:
            return by_body

    return None


def unrecorded_bugs(ctx: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for bug in ctx.get("bugs") or []:
        if bug.get("status") != "fixed" or not bug.get("commit"):
            missing.append(bug.get("finding_id") or "?")
    return missing


def bug_branch_is_merged(bug: dict[str, Any], repo_path: str) -> bool:
    branch = bug.get("branch")
    if not branch:
        return False
    git_run(["fetch", "origin", branch], repo_path, check=False)
    result = git_run(
        ["merge-base", "--is-ancestor", f"origin/{branch}", "HEAD"],
        repo_path,
        check=False,
    )
    return result.returncode == 0


def unmerged_bugs(ctx: dict[str, Any], repo_path: str) -> list[str]:
    missing: list[str] = []
    for bug in ctx.get("bugs") or []:
        if bug.get("status") != "fixed":
            continue
        if not bug.get("branch") or not bug_branch_is_merged(bug, repo_path):
            missing.append(bug.get("finding_id") or "?")
    return missing


def merge_conflict_files(repo_path: str) -> list[str]:
    result = git_run(
        ["diff", "--name-only", "--diff-filter=U"],
        repo_path,
        check=False,
    )
    if result.returncode != 0 and not result.stdout.strip():
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def run_resolve_gates(
    ctx: dict[str, Any],
    repo_path: str,
    *,
    require_verify: bool = False,
    verify_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    unrecorded = unrecorded_bugs(ctx)
    checks.append(
        {
            "name": "all_bugs_recorded",
            "ok": not unrecorded,
            "detail": ", ".join(unrecorded) if unrecorded else None,
        }
    )

    if not ctx.get("linked_pr"):
        ctx["linked_pr"] = resolve_linked_pr(ctx)
    checks.append(
        {
            "name": "linked_pr",
            "ok": bool(ctx.get("linked_pr")),
            "detail": None if ctx.get("linked_pr") else "no linked open PR found",
        }
    )

    unmerged = unmerged_bugs(ctx, repo_path)
    checks.append(
        {
            "name": "all_bugs_merged",
            "ok": not unmerged,
            "detail": ", ".join(unmerged) if unmerged else None,
        }
    )

    resolved_verify = verify_result
    if require_verify:
        if resolved_verify is None:
            resolved_verify = run_verify(ctx, repo_path)
        checks.append(
            {
                "name": "verify",
                "ok": bool(resolved_verify.get("ok")),
                "detail": None if resolved_verify.get("ok") else "verify failed",
            }
        )

    ok = all(check["ok"] for check in checks)
    output: dict[str, Any] = {"ok": ok, "checks": checks}
    if resolved_verify is not None:
        output["verify"] = resolved_verify
    return output


def hydrate_bugs_from_git(ctx: dict[str, Any], repo_path: str) -> list[str]:
    """Infer fixed bugs from merged remote branches when re-running after a partial run."""
    hydrated: list[str] = []
    task_branch = (ctx.get("task_branch") or {}).get("branch")
    if not task_branch:
        return hydrated

    git_run(["fetch", "origin", task_branch], repo_path, check=False)
    current = git_run(["branch", "--show-current"], repo_path, check=False)
    on_task = current.stdout.strip() == task_branch
    if not on_task:
        checkout = git_run(["checkout", task_branch], repo_path, check=False)
        if checkout.returncode != 0:
            git_run(
                ["checkout", "-b", task_branch, f"origin/{task_branch}"],
                repo_path,
                check=False,
            )

    for bug in ctx.get("bugs") or []:
        if bug.get("status") == "fixed" and bug.get("commit"):
            continue
        branch = bug.get("branch") or bug.get("proposed_branch")
        if not branch:
            continue
        git_run(["fetch", "origin", branch], repo_path, check=False)
        ref_check = git_run(
            ["show-ref", "--verify", f"refs/remotes/origin/{branch}"],
            repo_path,
            check=False,
        )
        if ref_check.returncode != 0:
            continue
        bug["branch"] = branch
        if not bug_branch_is_merged(bug, repo_path):
            continue
        sha = git_run(
            ["rev-parse", f"origin/{branch}"],
            repo_path,
            check=False,
        ).stdout.strip()
        if sha:
            bug["commit"] = sha
            bug["status"] = "fixed"
            hydrated.append(bug.get("finding_id") or "?")
    return hydrated


def collect_finding_sub_issues(
    sub_nodes: list[dict[str, Any]],
    task_ctx: dict[str, Any],
    *,
    finding_kind: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    open_bugs: list[dict[str, Any]] = []
    closed_bugs: list[dict[str, Any]] = []
    for node in sub_nodes:
        if not is_finding_sub_issue(node, finding_kind):
            continue
        if not extract_rr_id(node.get("title") or "", node.get("body") or ""):
            continue
        parsed = parse_bug_issue(node, task_ctx)
        state = (node.get("state") or "").upper()
        if state == "OPEN":
            open_bugs.append(parsed)
        else:
            parsed["status"] = "closed"
            closed_bugs.append(parsed)
    return open_bugs, closed_bugs


def build_resolve_context(
    task_repo: str,
    task_number: int,
    roots: list[Path],
    *,
    finding_kind: str = "bug",
) -> dict[str, Any]:
    normalized_finding_kind = normalize_finding_kind(finding_kind)
    finding_label = finding_kind_label(normalized_finding_kind)
    issue_data = fetch_issue_data(task_repo, task_number)
    body = issue_data.get("body") or ""
    title = issue_data.get("title") or ""
    if is_story_issue(body, title):
        task_ctx = build_story_context(task_repo, task_number, roots, issue_data)
    else:
        task_ctx = build_context(task_repo, task_number, roots)
    graph = issue_graph(task_repo, task_number)
    sub_nodes = []
    for node in (graph.get("subIssues") or {}).get("nodes") or []:
        sub_nodes.append(
            {
                "repo": node.get("repository", {}).get("nameWithOwner") or task_repo,
                "number": node.get("number"),
                "title": node.get("title"),
                "url": node.get("url"),
                "state": node.get("state"),
                "body": node.get("body") or "",
                "issue_type": (node.get("issueType") or {}).get("name"),
            }
        )

    open_bugs, closed_bugs = collect_finding_sub_issues(
        sub_nodes, task_ctx, finding_kind=normalized_finding_kind
    )
    bugs = open_bugs

    if not bugs:
        hint = (
            "pass --finding-kind task when RR findings are GitHub Task sub-issues"
            if normalized_finding_kind == "bug"
            else "pass --finding-kind bug when RR findings are GitHub Bug sub-issues"
        )
        if closed_bugs:
            if not task_ctx.get("scope_files"):
                task_ctx["scope_files"] = scope_files_from_bugs(closed_bugs)
            task_branch = task_ctx["task_branch"]["branch"]
            develop = list_issue_develop_branches(task_repo, task_number)
            if develop and not task_branch:
                task_branch = develop[0]
                task_ctx["task_branch"] = {
                    "branch": task_branch,
                    "source": "linked",
                    "exists_on_remote": True,
                }
            linked_prs = list_linked_prs(task_repo, task_number)
            ctx_pre = {
                **task_ctx,
                "issue_kind": task_ctx.get("issue_kind", "task"),
                "finding_kind": normalized_finding_kind,
                "resolve_issue": task_ctx["task_issue"],
                "bugs": [],
                "closed_bugs": closed_bugs,
                "linked_prs": linked_prs,
                "task_branch": task_ctx["task_branch"],
                "resolve_status": "complete",
                "resolve_message": (
                    f"no open {finding_label} RR sub-issues under {task_repo}#{task_number}; "
                    f"{len(closed_bugs)} already closed"
                ),
            }
            linked_pr = resolve_linked_pr(ctx_pre)
            if not task_branch:
                kind = resolve_issue_kind_label(task_ctx)
                raise SystemExit(
                    f"{kind} issue {task_repo}#{task_number} has no linked development branch; "
                    "link a branch via gh issue develop or add ## Development branches"
                )
            return {
                **ctx_pre,
                "linked_pr": linked_pr,
            }
        raise SystemExit(
            f"no open {finding_label} RR sub-issues under {task_repo}#{task_number}; "
            f"run /gh-review sync-bugs first, {hint}, or check issue hierarchy"
        )

    if not task_ctx.get("scope_files"):
        task_ctx["scope_files"] = scope_files_from_bugs(bugs)

    task_branch = task_ctx["task_branch"]["branch"]
    develop = list_issue_develop_branches(task_repo, task_number)
    if develop and not task_branch:
        task_branch = develop[0]
        task_ctx["task_branch"] = {
            "branch": task_branch,
            "source": "linked",
            "exists_on_remote": True,
        }

    linked_prs = list_linked_prs(task_repo, task_number)
    ctx_pre = {
        **task_ctx,
        "issue_kind": task_ctx.get("issue_kind", "task"),
        "finding_kind": normalized_finding_kind,
        "resolve_issue": task_ctx["task_issue"],
        "bugs": bugs,
        "linked_prs": linked_prs,
        "task_branch": task_ctx["task_branch"],
    }
    linked_pr = resolve_linked_pr(ctx_pre)

    if not task_branch:
        kind = resolve_issue_kind_label(task_ctx)
        raise SystemExit(
            f"{kind} issue {task_repo}#{task_number} has no linked development branch; "
            "link a branch via gh issue develop or add ## Development branches"
        )

    return {
        **ctx_pre,
        "linked_pr": linked_pr,
        "resolve_status": "open",
        "closed_bugs": closed_bugs,
    }


def find_bug(ctx: dict[str, Any], finding_id: str) -> dict[str, Any]:
    wanted = finding_id.upper()
    for bug in ctx.get("bugs") or []:
        if (bug.get("finding_id") or "").upper() == wanted:
            return bug
    raise SystemExit(f"bug {finding_id!r} not found in context")


def cmd_preflight(_args: argparse.Namespace) -> int:
    supported = _gsp.sub_issues_supported()
    print(f"sub_issues: {'supported' if supported else 'unavailable'}")
    try:
        subprocess.run(["gh", "auth", "status"], check=True, capture_output=True)
        print("gh_auth: ok")
    except subprocess.CalledProcessError:
        print("gh_auth: missing or expired")
        return 1
    return 0 if supported else 1


def cmd_context(args: argparse.Namespace) -> int:
    repo, number = parse_issue_spec(args.issue, default_repo=args.repo)
    roots = workspace_roots_from_args(args)
    ctx = build_resolve_context(
        repo,
        number,
        roots,
        finding_kind=args.finding_kind,
    )
    apply_pr_override(ctx, getattr(args, "pr", None))
    if getattr(args, "pr", None):
        ctx["linked_pr"] = ctx.get("linked_pr_override")
    repo_path = ctx.get("local_repo_path")
    if repo_path and ctx.get("resolve_status") != "complete":
        hydrated = hydrate_bugs_from_git(ctx, repo_path)
        if hydrated:
            ctx["hydrated_from_git"] = hydrated
    write_json(args.output, ctx)
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    repo, number = parse_issue_spec(args.issue, default_repo=args.repo)
    roots = workspace_roots_from_args(args)
    ctx = build_resolve_context(
        repo,
        number,
        roots,
        finding_kind=args.finding_kind,
    )
    apply_pr_override(ctx, getattr(args, "pr", None))
    if getattr(args, "pr", None):
        ctx["linked_pr"] = ctx.get("linked_pr_override")
    if ctx.get("resolve_status") == "complete":
        ctx["status_update"] = {
            "ok": True,
            "skipped": True,
            "reason": "no open bugs; prior run complete",
        }
        write_json(args.output, ctx)
        return 0
    repo_path = ctx.get("local_repo_path")
    if repo_path:
        hydrated = hydrate_bugs_from_git(ctx, repo_path)
        if hydrated:
            ctx["hydrated_from_git"] = hydrated
    if not ctx["blocker_gate"]["passed"]:
        ctx["status_update"] = {
            "ok": False,
            "skipped": True,
            "reason": "open blockers",
        }
        write_json(args.output, ctx)
        return 1
    project = ctx.get("project")
    status_result: dict[str, Any] = {"ok": False, "skipped": True, "reason": "no project"}
    if project:
        status_result = set_project_status(
            project, ctx["task_issue"]["url"], "in_progress"
        )
    ctx["status_update"] = status_result
    write_json(args.output, ctx)
    return 0


def cmd_checkout_task(args: argparse.Namespace) -> int:
    ctx = load_json(args.input)
    repo_path = args.repo_path or ctx.get("local_repo_path")
    if not repo_path:
        raise SystemExit("no local repo path; pass --repo-path")
    task_branch = ctx["task_branch"]["branch"]
    if not task_branch:
        raise SystemExit("task issue has no development branch")
    git_run(["fetch", "origin", task_branch], repo_path)
    current = git_run(["branch", "--show-current"], repo_path, check=False)
    if current.stdout.strip() != task_branch:
        checkout = git_run(
            ["checkout", task_branch],
            repo_path,
            check=False,
        )
        if checkout.returncode != 0:
            git_run(["checkout", "-b", task_branch, f"origin/{task_branch}"], repo_path)
    git_run(["pull", "--ff-only", "origin", task_branch], repo_path, check=False)
    result = {
        "repo_path": repo_path,
        "branch": task_branch,
        "current_branch": git_run(["branch", "--show-current"], repo_path).stdout.strip(),
    }
    ctx["checkout"] = result
    write_json(args.output, ctx)
    return 0


def cmd_create_bug_branch(args: argparse.Namespace) -> int:
    ctx = load_json(args.input)
    bug = find_bug(ctx, args.bug)
    repo_path = args.repo_path or ctx.get("local_repo_path")
    if not repo_path:
        raise SystemExit("no local repo path; pass --repo-path")
    task_branch = ctx["task_branch"]["branch"]
    bug_branch = bug.get("branch") or bug["proposed_branch"]

    if getattr(args, "worktree", False):
        # Branch off the local task_branch ref directly (not origin/) — it may have
        # commits from an in-progress /gh-build worktree that haven't been pushed yet.
        # Each bug gets its own worktree so parallel subagents never share a directory.
        worktree_path = _build.resolve_worktree_path(
            getattr(args, "worktree_root", None), repo_path, bug_branch
        )
        exists = git_run(
            ["show-ref", "--verify", f"refs/heads/{bug_branch}"], repo_path, check=False
        )
        if exists.returncode == 0:
            git_run(["worktree", "add", worktree_path, bug_branch], repo_path)
        else:
            git_run(["worktree", "add", "-b", bug_branch, worktree_path, task_branch], repo_path)
        git_run(["push", "-u", "origin", bug_branch], worktree_path, check=False)
        bug["branch"] = bug_branch
        bug["worktree_path"] = worktree_path
        result = {
            "finding_id": bug["finding_id"],
            "branch": bug_branch,
            "base": task_branch,
            "repo_path": worktree_path,
            "worktree_path": worktree_path,
            "main_repo_path": repo_path,
        }
        write_json(args.output, {**ctx, "bug_branch": result})
        return 0

    git_run(["fetch", "origin", task_branch], repo_path)
    git_run(["checkout", task_branch], repo_path)
    git_run(["pull", "--ff-only", "origin", task_branch], repo_path, check=False)
    exists = git_run(["show-ref", "--verify", f"refs/heads/{bug_branch}"], repo_path, check=False)
    if exists.returncode != 0:
        remote = git_run(
            ["show-ref", "--verify", f"refs/remotes/origin/{bug_branch}"],
            repo_path,
            check=False,
        )
        if remote.returncode == 0:
            git_run(["checkout", "-b", bug_branch, f"origin/{bug_branch}"], repo_path)
        else:
            git_run(["checkout", "-b", bug_branch], repo_path)
    else:
        git_run(["checkout", bug_branch], repo_path)
    git_run(["push", "-u", "origin", bug_branch], repo_path, check=False)
    bug["branch"] = bug_branch
    result = {
        "finding_id": bug["finding_id"],
        "branch": bug_branch,
        "base": task_branch,
        "repo_path": repo_path,
    }
    write_json(args.output, {**ctx, "bug_branch": result})
    return 0


def render_bug_commit_message(bug: dict[str, Any], task_ctx: dict[str, Any]) -> str:
    task = task_ctx["task_issue"]
    story = task_ctx["story_issue"]
    scope_hint = Path(bug["scope_files"][0]).stem if bug.get("scope_files") else "bug"
    summary = (bug.get("summary") or "fix bug").splitlines()[0].strip()
    return (
        f"fix({scope_hint}): {summary} "
        f"({bug['finding_id']}, {story['id']}, {task['repo']}#{task['number']})"
    )


def cmd_commit_push(args: argparse.Namespace) -> int:
    ctx = load_json(args.input)
    bug = find_bug(ctx, args.bug)
    repo_path = args.repo_path or ctx.get("local_repo_path")
    if not repo_path:
        raise SystemExit("no local repo path; pass --repo-path")
    branch = bug.get("branch") or bug.get("proposed_branch")
    files = list(
        dict.fromkeys((bug.get("scope_files") or []) + (bug.get("test_files") or []))
    )
    message = args.message or render_bug_commit_message(bug, ctx)
    if args.dry_run:
        write_json(
            args.output,
            {
                "dry_run": True,
                "repo_path": repo_path,
                "branch": branch,
                "files": files,
                "message": message,
            },
        )
        return 0
    if branch:
        git_run(["checkout", branch], repo_path)
    if files:
        git_run(["add", *files], repo_path)
    git_run(["commit", "-m", message], repo_path)
    git_run(["push", "-u", "origin", "HEAD"], repo_path)
    sha = git_run(["rev-parse", "HEAD"], repo_path).stdout.strip()
    bug["commit"] = sha
    bug["status"] = "fixed"
    result = {
        "finding_id": bug["finding_id"],
        "branch": branch,
        "commit": sha,
        "message": message,
        "files": files,
    }
    write_json(args.output, {**ctx, "commit": result})
    return 0


def cmd_merge_bugs(args: argparse.Namespace) -> int:
    ctx = load_json(args.input)
    repo_path = args.repo_path or ctx.get("local_repo_path")
    if not repo_path:
        raise SystemExit("no local repo path; pass --repo-path")
    task_branch = ctx["task_branch"]["branch"]

    unrecorded = unrecorded_bugs(ctx)
    if unrecorded:
        raise SystemExit(
            f"merge-bugs: {len(unrecorded)}/{len(ctx.get('bugs') or [])} bugs not recorded; "
            f"run record-bug for {', '.join(unrecorded)}"
        )

    fixed = [b for b in ctx.get("bugs") or [] if b.get("status") == "fixed" and b.get("branch")]
    if not fixed:
        raise SystemExit("no fixed bugs with branches to merge")

    git_run(["fetch", "origin"], repo_path)
    git_run(["checkout", task_branch], repo_path)
    git_run(["pull", "--ff-only", "origin", task_branch], repo_path, check=False)

    merged: list[dict[str, Any]] = []
    for bug in fixed:
        branch = bug["branch"]
        git_run(["fetch", "origin", branch], repo_path)
        if bug_branch_is_merged(bug, repo_path):
            merged.append(
                {"finding_id": bug["finding_id"], "branch": branch, "skipped": True}
            )
            continue
        merge = git_run(
            [
                "merge",
                "--no-ff",
                f"origin/{branch}",
                "-m",
                f"Merge {branch} ({bug['finding_id']})",
            ],
            repo_path,
            check=False,
        )
        if merge.returncode != 0:
            conflicts = merge_conflict_files(repo_path)
            git_run(["merge", "--abort"], repo_path, check=False)
            result = {
                "task_branch": task_branch,
                "merged": merged,
                "failed": {
                    "finding_id": bug["finding_id"],
                    "branch": branch,
                    "conflict_files": conflicts,
                },
            }
            write_json(args.output, {**ctx, "merge": result})
            raise SystemExit(
                f"merge failed for {branch} ({bug['finding_id']}): "
                f"conflicts in {', '.join(conflicts) or 'unknown files'}; "
                "resolve on task branch, commit, re-run merge-bugs"
            )
        merged.append({"finding_id": bug["finding_id"], "branch": branch, "skipped": False})

    git_run(["push", "origin", task_branch], repo_path)
    result = {"task_branch": task_branch, "merged": merged}
    write_json(args.output, {**ctx, "merge": result})
    return 0


def render_pr_update(ctx: dict[str, Any]) -> str:
    task = ctx["task_issue"]
    kind = resolve_issue_kind_label(ctx)
    fixed = [b for b in ctx.get("bugs") or [] if b.get("status") == "fixed"]
    lines = [
        "## Bug fixes resolved",
        "",
        f"Resolved via `/gh-resolve-issues` on {kind} {task['repo']}#{task['number']}.",
        "",
    ]
    for bug in fixed:
        test_note = ", ".join(f"`{f}`" for f in bug.get("test_files") or []) or "_tests added in commit_"
        lines.append(
            f"- [x] **{bug['finding_id']}** — {bug.get('summary', '')} "
            f"({bug.get('url', '')}); tests: {test_note}"
        )
    lines.extend(["", "## Regression tests", ""])
    for bug in fixed:
        if bug.get("test_files"):
            for path in bug["test_files"]:
                lines.append(f"- [x] `{path}` — {bug['finding_id']}")
        else:
            lines.append(f"- [ ] {bug['finding_id']} — no automated test (documented in issue)")
    verify = ctx.get("verify_cmd") or ""
    if verify:
        lines.extend(["", "## Verify", "", f"- [x] `{verify}`"])
    return "\n".join(lines) + "\n"


def cmd_update_pr(args: argparse.Namespace) -> int:
    ctx = load_json(args.input)
    if not ctx.get("linked_pr"):
        ctx["linked_pr"] = resolve_linked_pr(ctx)
    pr = ctx.get("linked_pr")
    if not pr:
        raise SystemExit("no linked open PR on task issue; cannot update")
    pr_repo = pr["repo"]
    pr_number = int(pr["number"])
    data = gh_json(
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            pr_repo,
            "--json",
            "body,url",
        ]
    )
    body = data.get("body") or ""
    update_block = render_pr_update(ctx)
    marker = "## Bug fixes resolved"
    if marker in body:
        prefix = body.split(marker, 1)[0].rstrip()
        new_body = prefix + "\n\n" + update_block
    else:
        new_body = body.rstrip() + "\n\n" + update_block
    if args.dry_run:
        pr_update = {"dry_run": True, "pr_url": data.get("url"), "body": new_body}
        write_json(args.output, {**ctx, "pr_update": pr_update})
        return 0
    gh_run(
        [
            "pr",
            "edit",
            str(pr_number),
            "--repo",
            pr_repo,
            "--body",
            new_body,
        ]
    )
    pr_update = {"ok": True, "pr_url": data.get("url"), "updated": True}
    write_json(args.output, {**ctx, "pr_update": pr_update})
    return 0


def cmd_close_bugs(args: argparse.Namespace) -> int:
    ctx = load_json(args.input)
    repo_path = args.repo_path or ctx.get("local_repo_path")
    if not repo_path:
        raise SystemExit("no local repo path; pass --repo-path")

    allow_partial = getattr(args, "allow_partial", False)
    if not allow_partial:
        unrecorded = unrecorded_bugs(ctx)
        if unrecorded:
            raise SystemExit(
                f"close-bugs: bugs not recorded: {', '.join(unrecorded)}; "
                "run record-bug first or pass --allow-partial"
            )
        unmerged = unmerged_bugs(ctx, repo_path)
        if unmerged:
            raise SystemExit(
                f"close-bugs: bugs not merged on task branch: {', '.join(unmerged)}; "
                "run merge-bugs first or pass --allow-partial"
            )

    fixed = [b for b in ctx.get("bugs") or [] if b.get("status") == "fixed"]
    if not fixed:
        raise SystemExit("no fixed bugs to close")
    closed: list[dict[str, Any]] = []
    task = ctx["task_issue"]
    branch_label = (
        "story branch" if ctx.get("issue_kind") == "story" else "task branch"
    )
    for bug in fixed:
        repo = bug.get("repo") or task["repo"]
        number = int(bug["number"])
        issue_data = fetch_issue_data(repo, number)
        if (issue_data.get("state") or "").upper() == "CLOSED":
            bug["status"] = "closed"
            closed.append(
                {
                    "finding_id": bug["finding_id"],
                    "repo": repo,
                    "number": number,
                    "url": bug.get("url"),
                    "skipped": True,
                }
            )
            continue
        comment = (
            f"Fixed on {branch_label} `{ctx['task_branch']['branch']}` "
            f"(commit {bug.get('commit') or 'see PR'}). "
            f"Regression tests: {', '.join(bug.get('test_files') or []) or 'see PR test plan'}."
        )
        if args.dry_run:
            closed.append({"finding_id": bug["finding_id"], "dry_run": True})
            continue
        close_issue(repo, number, comment)
        bug["status"] = "closed"
        closed.append(
            {
                "finding_id": bug["finding_id"],
                "repo": repo,
                "number": number,
                "url": bug.get("url"),
            }
        )
    write_json(args.output, {**ctx, "closed_bugs": closed})
    return 0


def cmd_record_bug(args: argparse.Namespace) -> int:
    ctx = load_json(args.input)
    bug = find_bug(ctx, args.bug)
    if bug.get("status") == "fixed" and bug.get("commit") == args.commit:
        result = {
            "finding_id": bug["finding_id"],
            "commit": args.commit,
            "github_closed": bug.get("status") == "closed",
            "note": "already recorded; call close-bugs after verify passes",
            "skipped": True,
        }
        write_json(args.output or args.input, {**ctx, "record_bug": result})
        return 0
    bug["status"] = "fixed"
    bug["commit"] = args.commit
    if args.test_file:
        existing = list(bug.get("test_files") or [])
        for path in args.test_file:
            if path not in existing:
                existing.append(path)
        bug["test_files"] = existing
    result = {
        "finding_id": bug["finding_id"],
        "commit": args.commit,
        "github_closed": False,
        "note": "call close-bugs after verify passes",
    }
    write_json(args.output or args.input, {**ctx, "record_bug": result})
    return 0


def cmd_gates(args: argparse.Namespace) -> int:
    ctx = load_json(args.input)
    repo_path = args.repo_path or ctx.get("local_repo_path")
    if not repo_path:
        raise SystemExit("no local repo path; pass --repo-path")
    verify_result = (
        load_json(args.verify_result) if getattr(args, "verify_result", None) else None
    )
    result = run_resolve_gates(
        ctx,
        repo_path,
        require_verify=getattr(args, "require_verify", False),
        verify_result=verify_result,
    )
    ctx["gates"] = result
    if result.get("verify"):
        ctx["verify"] = result["verify"]
    write_json(args.output or args.input, {**ctx, **result})
    return 0 if result.get("ok") else 1


def resolve_verify_result(
    ctx: dict[str, Any],
    repo_path: str,
    *,
    verify_result_path: str | None = None,
) -> dict[str, Any]:
    if verify_result_path:
        return load_json(verify_result_path)
    return run_verify(ctx, repo_path)


def cmd_verify(args: argparse.Namespace) -> int:
    ctx = load_json(args.input)
    repo_path = args.repo_path or ctx.get("local_repo_path")
    if not repo_path:
        raise SystemExit("no local repo path; pass --repo-path")
    result = run_verify(ctx, repo_path)
    ctx["verify"] = result
    write_json(args.output, result)
    return 0 if result.get("ok") else 1


def cmd_finish(args: argparse.Namespace) -> int:
    ctx_path = args.input
    out_path = args.output or ctx_path
    require_verify = getattr(args, "require_verify", True)

    ctx = load_json(ctx_path)
    if ctx.get("resolve_status") == "complete":
        write_json(
            out_path,
            {
                "ok": True,
                "skipped": True,
                "reason": "no open bugs; prior run complete",
                "task_issue": ctx["task_issue"],
                "linked_pr": ctx.get("linked_pr"),
                "closed_bugs": ctx.get("closed_bugs"),
                "resolve_status": "complete",
            },
        )
        return 0

    repo_path = args.repo_path or ctx.get("local_repo_path")
    if repo_path:
        hydrated = hydrate_bugs_from_git(ctx, repo_path)
        if hydrated:
            ctx["hydrated_from_git"] = hydrated
            write_json(ctx_path, ctx)

    merge_args = argparse.Namespace(
        input=ctx_path,
        repo_path=args.repo_path,
        output=ctx_path,
        dry_run=False,
    )
    cmd_merge_bugs(merge_args)

    ctx = load_json(ctx_path)
    apply_pr_override(ctx, getattr(args, "pr", None))
    if getattr(args, "pr", None):
        ctx["linked_pr"] = ctx.get("linked_pr_override")
        write_json(ctx_path, ctx)

    repo_path = args.repo_path or ctx.get("local_repo_path")
    if not repo_path:
        raise SystemExit("no local repo path; pass --repo-path")

    verify_result: dict[str, Any] | None = None
    if getattr(args, "verify_result", None):
        loaded = load_json(args.verify_result)
        if isinstance(loaded, dict) and "checks" in loaded:
            verify_result = loaded.get("verify")
        else:
            verify_result = loaded

    gates_result = run_resolve_gates(
        ctx,
        repo_path,
        require_verify=require_verify,
        verify_result=verify_result,
    )
    ctx["gates"] = gates_result
    if gates_result.get("verify"):
        ctx["verify"] = gates_result["verify"]
    write_json(ctx_path, ctx)

    if not gates_result.get("ok"):
        write_json(
            out_path,
            {
                "ok": False,
                "task_issue": ctx["task_issue"],
                "linked_pr": ctx.get("linked_pr"),
                "merge": ctx.get("merge"),
                "gates": gates_result,
                "verify": gates_result.get("verify"),
                "closed_bugs": None,
                "bugs": ctx.get("bugs"),
                "error": "gates failed; fix on task branch and re-run gates or finish",
            },
        )
        return 1

    update_args = argparse.Namespace(
        input=ctx_path, output=ctx_path, dry_run=False, repo_path=args.repo_path
    )
    cmd_update_pr(update_args)

    close_args = argparse.Namespace(
        input=ctx_path,
        output=ctx_path,
        dry_run=False,
        repo_path=args.repo_path,
        allow_partial=False,
    )
    cmd_close_bugs(close_args)

    final = load_json(ctx_path)
    status_update: dict[str, Any] = {"ok": False, "skipped": True, "reason": "no project"}
    project = final.get("project") or ctx.get("project")
    if project:
        status_update = set_project_status(
            project, final["task_issue"]["url"], "ready_to_ship"
        )
    write_json(
        out_path,
        {
            "ok": True,
            "task_issue": final["task_issue"],
            "linked_pr": final.get("linked_pr"),
            "merge": final.get("merge"),
            "gates": final.get("gates"),
            "verify": final.get("verify") or verify_result,
            "closed_bugs": final.get("closed_bugs"),
            "bugs": final.get("bugs"),
            "status_update": status_update,
        },
    )
    return 0


_AUTO_DIR = _SCRIPT_DIR.parent / "auto"


def _load_merge_policy():
    return _load_module("auto_merge_policy", _AUTO_DIR / "merge_policy.py")


def cmd_check_merge_allowed(args: argparse.Namespace) -> int:
    policy = _load_merge_policy()
    decision = policy.can_agent_merge_pr(
        issue_type=args.issue_type,
        is_review_finding=bool(args.finding),
        branch=args.branch,
        labels=args.label or [],
    )
    print(json.dumps(decision, indent=2))
    return 0 if decision.get("allowed") else 2


def cmd_merge_finding_pr(args: argparse.Namespace) -> int:
    """Merge a finding PR only after merge_policy allows it (Phase 5)."""
    policy = _load_merge_policy()
    policy.assert_agent_may_merge(
        issue_type=args.issue_type,
        is_review_finding=bool(args.finding) or args.issue_type == "Bug",
        branch=args.branch,
        labels=args.label or [],
    )
    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "pr": args.pr, "repo": args.repo}))
        return 0
    result = subprocess.run(
        [
            "gh",
            "pr",
            "merge",
            str(args.pr),
            "--repo",
            args.repo,
            "--squash",
            "--delete-branch",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        return result.returncode
    print(json.dumps({"ok": True, "merged": True, "pr": args.pr, "repo": args.repo}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("preflight", help="Check gh auth and sub-issue support")

    def add_issue_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--issue", help="Task issue URL or OWNER/REPO#N")
        p.add_argument("--repo", help="Default repo when --issue is a number")
        p.add_argument(
            "--pr",
            help="Linked PR URL override (e.g. https://github.com/org/repo/pull/115)",
        )
        p.add_argument("--output", "-o", help="Write JSON result to path")
        p.add_argument(
            "--workspace-root",
            action="append",
            help="Workspace root for local repo discovery (repeatable)",
        )
        p.add_argument(
            "--finding-kind",
            choices=FINDING_KINDS,
            default="bug",
            help=(
                "GitHub sub-issue type for RR findings (default: bug). "
                "Use task when /gh-review filed findings as Task sub-issues."
            ),
        )

    def add_input_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--input", required=True, help="Context JSON path")
        p.add_argument("--output", "-o", help="Write JSON result to path")
        p.add_argument("--repo-path", help="Local git checkout path")
        p.add_argument("--dry-run", action="store_true")

    ctx = sub.add_parser("context", help="Parse task/story issue + RR sub-issues")
    add_issue_args(ctx)

    start = sub.add_parser("start", help="context + set Status In-progress")
    add_issue_args(start)

    checkout = sub.add_parser("checkout-task", help="Checkout task issue branch")
    add_input_args(checkout)

    bug_branch = sub.add_parser("create-bug-branch", help="Create bug fix branch from task branch")
    add_input_args(bug_branch)
    bug_branch.add_argument("--bug", required=True, help="Finding id e.g. RR-01")
    bug_branch.add_argument(
        "--worktree",
        action="store_true",
        help="Create the bug branch in its own linked git worktree (for parallel subagents)",
    )
    bug_branch.add_argument(
        "--worktree-root",
        help="Directory to create bug worktrees under (default: sibling '<repo>-worktrees/' dir)",
    )

    commit = sub.add_parser("commit-push", help="Commit bug fix on bug branch")
    add_input_args(commit)
    commit.add_argument("--bug", required=True, help="Finding id e.g. RR-01")
    commit.add_argument("--message", help="Override commit message")

    merge = sub.add_parser("merge-bugs", help="Merge fixed bug branches into task branch")
    add_input_args(merge)

    gates = sub.add_parser(
        "gates",
        help="Pre-close checks: all bugs recorded, merged, linked PR, optional verify",
    )
    add_input_args(gates)
    gates.add_argument(
        "--require-verify",
        action="store_true",
        help="Include verify step in gate checks",
    )
    gates.add_argument(
        "--verify-result",
        help="Prior verify JSON output (skip re-running verify during gates)",
    )

    verify = sub.add_parser(
        "verify",
        help="Run task verify command, full suite, and build checks on task branch",
    )
    add_input_args(verify)

    update = sub.add_parser("update-pr", help="Update linked PR test plan")
    add_input_args(update)

    close = sub.add_parser("close-bugs", help="Close fixed Bug sub-issues")
    add_input_args(close)
    close.add_argument(
        "--allow-partial",
        action="store_true",
        help="Close fixed bugs even when not all are recorded/merged (emergency only)",
    )

    record = sub.add_parser("record-bug", help="Mark bug fixed after subagent push")
    add_input_args(record)
    record.add_argument("--bug", required=True, help="Finding id e.g. RR-01")
    record.add_argument("--commit", required=True, help="Commit SHA on bug branch")
    record.add_argument(
        "--test-file",
        action="append",
        help="Regression test file path (repeatable)",
    )

    finish = sub.add_parser(
        "finish",
        help="merge-bugs + gates + update-pr + close-bugs",
    )
    add_input_args(finish)
    finish.add_argument(
        "--pr",
        help="Linked PR URL override (e.g. https://github.com/org/repo/pull/115)",
    )
    finish.add_argument(
        "--require-verify",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run verify after merge; abort before update-pr/close-bugs when verify fails (default: on)",
    )
    finish.add_argument(
        "--verify-result",
        help="Prior verify JSON output (skip re-running verify during finish)",
    )

    check_merge = sub.add_parser(
        "check-merge-allowed",
        help="Phase 5: check whether an agent may merge this issue's PR",
    )
    check_merge.add_argument("--issue-type", required=True)
    check_merge.add_argument(
        "--finding",
        action="store_true",
        help="Mark as review-generated finding (required for Task findings)",
    )
    check_merge.add_argument("--branch", default=None)
    check_merge.add_argument("--label", action="append", default=[])

    merge_finding = sub.add_parser(
        "merge-finding-pr",
        help="Phase 5: merge a finding PR after merge_policy allowlist check",
    )
    merge_finding.add_argument("--repo", required=True)
    merge_finding.add_argument("--pr", required=True, help="PR number or URL")
    merge_finding.add_argument("--issue-type", required=True)
    merge_finding.add_argument("--finding", action="store_true")
    merge_finding.add_argument("--branch", default=None)
    merge_finding.add_argument("--label", action="append", default=[])
    merge_finding.add_argument("--dry-run", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "preflight": cmd_preflight,
        "context": cmd_context,
        "start": cmd_start,
        "checkout-task": cmd_checkout_task,
        "create-bug-branch": cmd_create_bug_branch,
        "commit-push": cmd_commit_push,
        "merge-bugs": cmd_merge_bugs,
        "gates": cmd_gates,
        "verify": cmd_verify,
        "update-pr": cmd_update_pr,
        "close-bugs": cmd_close_bugs,
        "record-bug": cmd_record_bug,
        "finish": cmd_finish,
        "check-merge-allowed": cmd_check_merge_allowed,
        "merge-finding-pr": cmd_merge_finding_pr,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
