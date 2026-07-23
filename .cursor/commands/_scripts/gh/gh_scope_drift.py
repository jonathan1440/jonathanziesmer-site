"""Scope drift detection for /gh-update-plan."""

from __future__ import annotations

import subprocess
from typing import Any, Callable

from gh_git_helpers import git_run
from gh_plan_messages import render_update_plan_outcome
from gh_plan_parsers import parse_scope_files_optional


def _git_output(args: list[str], repo_path: str) -> str:
    return git_run(args, repo_path, check=True).stdout.strip()


def _rev_exists(repo_path: str, rev: str) -> bool:
    proc = git_run(["rev-parse", "-q", "--verify", f"{rev}^{{commit}}"], repo_path, check=False)
    return proc.returncode == 0


def _fetch_refs(repo_path: str, *refs: str) -> None:
    existing = [ref for ref in refs if ref]
    if existing:
        git_run(["fetch", "origin", *existing], repo_path, check=False)


def _path_changed_in_range(
    repo_path: str,
    path: str,
    *,
    pre_sha: str | None,
    post_sha: str | None,
    spec_branch: str,
    story_branch: str,
    use_home_shas: bool,
) -> bool:
    _fetch_refs(repo_path, spec_branch, story_branch)
    if use_home_shas and pre_sha and post_sha and _rev_exists(repo_path, pre_sha) and _rev_exists(repo_path, post_sha):
        diff_args = ["diff", "--name-only", pre_sha, post_sha, "--", path]
    else:
        if not _rev_exists(repo_path, f"origin/{spec_branch}") or not _rev_exists(repo_path, f"origin/{story_branch}"):
            return False
        diff_args = ["diff", "--name-only", f"origin/{spec_branch}", f"origin/{story_branch}", "--", path]
    try:
        out = _git_output(diff_args, repo_path)
    except subprocess.CalledProcessError:
        return False
    return bool(out.strip())


def collect_scope_paths_by_repo(
    manifest: dict[str, Any],
    story_id: str,
    *,
    fetch_issue_body: Callable[[str, int], str] | None = None,
) -> dict[str, list[str]]:
    """Map owner/repo → unique scope file paths for the story."""
    by_repo: dict[str, list[str]] = {}
    work_issues = manifest.get("work_issues") or {}

    for _task_id, entry in work_issues.items():
        if entry.get("story_id") != story_id:
            continue
        repo = entry.get("repo")
        if not repo:
            continue
        paths: list[str] = list(entry.get("files") or [])
        if not paths and fetch_issue_body:
            number = entry.get("number")
            if number:
                body = fetch_issue_body(repo, int(number))
                paths = parse_scope_files_optional(body)
        if not paths:
            continue
        bucket = by_repo.setdefault(repo, [])
        for path in paths:
            if path not in bucket:
                bucket.append(path)
    return by_repo


def check_scope_drift_core(
    *,
    manifest: dict[str, Any],
    story_id: str,
    home_repo: str,
    repo_path: str,
    pre_story_sha: str | None,
    post_story_sha: str | None,
    spec_branch: str,
    story_branch: str,
    other_repos: list[dict[str, str]] | None = None,
    fetch_issue_body: Callable[[str, int], str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "story_id": story_id,
        "home_repo": home_repo,
        "pre_story_sha": pre_story_sha,
        "post_story_sha": post_story_sha,
        "scope_paths_checked": [],
        "drifted_paths": [],
        "skipped_repos": [],
        "outcome": "unchanged",
        "user_message": None,
    }

    if not post_story_sha or pre_story_sha == post_story_sha:
        result["user_message"] = render_update_plan_outcome("unchanged")
        return result

    scope_by_repo = collect_scope_paths_by_repo(
        manifest,
        story_id,
        fetch_issue_body=fetch_issue_body,
    )
    checkout_map: dict[str, str] = {home_repo: repo_path}
    for other in other_repos or []:
        gh_repo = other.get("repo")
        path = other.get("path")
        if gh_repo and path:
            checkout_map[gh_repo] = path

    drifted: list[dict[str, str]] = []
    checked: list[dict[str, str]] = []

    for repo, paths in scope_by_repo.items():
        checkout = checkout_map.get(repo)
        if not checkout:
            result["skipped_repos"].append(repo)
            continue
        use_home_shas = repo == home_repo
        for path in paths:
            checked.append(
                {
                    "repo": repo,
                    "path": path,
                    "method": "pre_post" if use_home_shas else "spec_story",
                }
            )
            if _path_changed_in_range(
                checkout,
                path,
                pre_sha=pre_story_sha,
                post_sha=post_story_sha,
                spec_branch=spec_branch,
                story_branch=story_branch,
                use_home_shas=use_home_shas,
            ):
                drifted.append({"repo": repo, "path": path})

    result["scope_paths_checked"] = checked
    result["drifted_paths"] = drifted
    result["outcome"] = "drift" if drifted else "synced_valid"
    result["user_message"] = render_update_plan_outcome(result["outcome"], drifted)
    return result
