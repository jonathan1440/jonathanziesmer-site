"""Branch sync and started-gate checks for /gh-plan and /gh-update-plan."""

from __future__ import annotations

from typing import Any

from gh_git_helpers import git_run


def _git_output(args: list[str], repo_path: str) -> str:
    result = git_run(args, repo_path, check=True)
    return (result.stdout or "").strip()


def _git_output_optional(args: list[str], repo_path: str) -> str | None:
    result = git_run(args, repo_path, check=False)
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip()


def _remote_exists(repo_path: str, ref: str) -> bool:
    return (
        git_run(["rev-parse", "--verify", ref], repo_path, check=False).returncode
        == 0
    )


def _rev_list_count(repo_path: str, range_spec: str, *, no_merges: bool = False) -> int:
    args = ["rev-list", "--count"]
    if no_merges:
        args.append("--no-merges")
    args.append(range_spec)
    out = _git_output_optional(args, repo_path)
    if out is None:
        return 0
    try:
        return int(out)
    except ValueError:
        return 0


def _sample_shas(repo_path: str, range_spec: str, *, limit: int = 3) -> list[str]:
    out = _git_output_optional(
        ["rev-list", "--no-merges", f"--max-count={limit}", range_spec],
        repo_path,
    )
    if not out:
        return []
    return out.splitlines()


def spec_branch_started(
    repo_path: str,
    default: str,
    spec_branch: str,
    slug: str,
) -> dict[str, Any]:
    range_spec = f"origin/{default}..origin/{spec_branch}"
    log = _git_output_optional(
        [
            "log",
            range_spec,
            "--no-merges",
            "--pretty=format:",
            "--name-only",
        ],
        repo_path,
    )
    prefix = f"docs/specs/{slug}/"
    impl_files: list[str] = []
    if log:
        for line in log.splitlines():
            line = line.strip()
            if not line or line.startswith(prefix):
                continue
            impl_files.append(line)
            break
    count = _rev_list_count(repo_path, range_spec, no_merges=True)
    started = bool(impl_files)
    return {
        "started": started,
        "non_merge_count": count,
        "sample_shas": _sample_shas(repo_path, range_spec),
        "impl_file_sample": impl_files[:1],
    }


def story_branch_started(
    repo_path: str,
    spec_branch: str,
    story_branch: str,
) -> dict[str, Any]:
    if not _remote_exists(repo_path, f"origin/{story_branch}"):
        return {"started": False, "non_merge_count": 0, "sample_shas": [], "missing_remote": True}
    range_spec = f"origin/{spec_branch}..origin/{story_branch}"
    count = _rev_list_count(repo_path, range_spec, no_merges=True)
    return {
        "started": count > 0,
        "non_merge_count": count,
        "sample_shas": _sample_shas(repo_path, range_spec),
        "missing_remote": False,
    }


def task_branch_started(
    repo_path: str,
    task_branch: str,
    story_branch: str,
    spec_branch: str,
) -> dict[str, Any]:
    if not _remote_exists(repo_path, f"origin/{task_branch}"):
        return {"started": False, "non_merge_count": 0, "sample_shas": []}
    base = _git_output_optional(
        ["merge-base", f"origin/{story_branch}", f"origin/{task_branch}"],
        repo_path,
    )
    if not base:
        base = _git_output_optional(
            ["merge-base", f"origin/{spec_branch}", f"origin/{task_branch}"],
            repo_path,
        )
    if not base:
        return {"started": False, "non_merge_count": 0, "sample_shas": []}
    range_spec = f"{base}..origin/{task_branch}"
    count = _rev_list_count(repo_path, range_spec, no_merges=True)
    return {
        "started": count > 0,
        "non_merge_count": count,
        "sample_shas": _sample_shas(repo_path, range_spec),
    }


def _conflict_files(repo_path: str) -> list[str]:
    out = _git_output_optional(
        ["diff", "--name-only", "--diff-filter=U"],
        repo_path,
    )
    if not out:
        return []
    return [line for line in out.splitlines() if line.strip()]


def _default_is_ahead(repo_path: str, default: str, spec_branch: str) -> bool:
    return _rev_list_count(repo_path, f"origin/{spec_branch}..origin/{default}") > 0


def _spec_is_ahead_of_story(repo_path: str, spec_branch: str, story_branch: str) -> bool:
    if not _remote_exists(repo_path, f"origin/{story_branch}"):
        return True
    return _rev_list_count(repo_path, f"origin/{story_branch}..origin/{spec_branch}") > 0


def sync_other_listed_repo(
    repo_path: str,
    spec_branch: str,
    story_branch: str,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {"repo_path": repo_path, "actions": []}
    if dry_run:
        result["actions"].append("dry-run: would fetch and checkout story or spec branch")
        return result
    git_run(["fetch", "origin"], repo_path, check=True)
    for branch in (story_branch, spec_branch):
        checkout = git_run(["checkout", branch], repo_path, check=False)
        if checkout.returncode == 0:
            result["checked_out"] = branch
            result["actions"].append(f"checked out {branch}")
            return result
    result["actions"].append("no matching story or spec branch to checkout")
    return result


def sync_plan_branches_core(
    *,
    home_repo: str,
    repo_path: str,
    default: str,
    spec_branch: str,
    story_branch: str,
    feature_slug: str,
    mode: str = "plan",
    work_issues: dict[str, Any] | None = None,
    story_id: str | None = None,
    other_repos: list[dict[str, str]] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sync home-repo branches; return structured status for the agent."""
    result: dict[str, Any] = {
        "home_repo": home_repo,
        "repo_path": repo_path,
        "mode": mode,
        "default_branch": default,
        "spec_branch": spec_branch,
        "story_branch": story_branch,
        "feature_slug": feature_slug,
        "actions": [],
        "blocked_reason": None,
        "require_user_confirm": False,
        "conflicts": [],
        "pre_story_sha": None,
        "post_story_sha": None,
        "branches": {},
        "other_repos": [],
    }

    fetch_refs = [default, spec_branch]
    if _remote_exists(repo_path, f"origin/{story_branch}"):
        fetch_refs.append(story_branch)
    if not dry_run:
        git_run(["fetch", "origin", *fetch_refs], repo_path, check=True)

    spec_status = spec_branch_started(repo_path, default, spec_branch, feature_slug)
    story_status = story_branch_started(repo_path, spec_branch, story_branch)
    result["branches"]["spec"] = {"branch": spec_branch, **spec_status}
    result["branches"]["story"] = {
        "branch": story_branch,
        **story_status,
    }

    started_rows: list[dict[str, Any]] = []
    if spec_status["started"]:
        started_rows.append(
            {
                "kind": "spec",
                "branch": spec_branch,
                "repo": home_repo,
                **spec_status,
            }
        )
    if story_status.get("started"):
        started_rows.append(
            {
                "kind": "story",
                "branch": story_branch,
                "repo": home_repo,
                **story_status,
            }
        )

    if work_issues and story_id:
        result["branches"]["tasks"] = []
        for task_id, entry in work_issues.items():
            if entry.get("story_id") != story_id:
                continue
            task_branch = entry.get("branch")
            task_repo = entry.get("repo")
            if not task_branch or not task_repo:
                continue
            task_path = entry.get("_repo_path")
            if not task_path:
                continue
            task_status = task_branch_started(
                task_path, task_branch, story_branch, spec_branch
            )
            row = {
                "task_id": task_id,
                "branch": task_branch,
                "repo": task_repo,
                **task_status,
            }
            result["branches"]["tasks"].append(row)
            if task_status["started"]:
                started_rows.append({"kind": "task", **row})

    if started_rows:
        result["started_branches"] = started_rows
        if mode == "update-plan":
            result["blocked_reason"] = "implementation_in_progress"
        else:
            result["blocked_reason"] = "branch_started"
            result["require_user_confirm"] = True
        return result

    if _remote_exists(repo_path, f"origin/{story_branch}"):
        result["pre_story_sha"] = _git_output_optional(
            ["rev-parse", f"origin/{story_branch}"],
            repo_path,
        )

    spec_not_started = not spec_status["started"]
    story_not_started = not story_status.get("started")

    if spec_not_started and _default_is_ahead(repo_path, default, spec_branch):
        action = f"rebase {spec_branch} onto origin/{default}"
        result["actions"].append(action)
        if not dry_run:
            git_run(["checkout", spec_branch], repo_path, check=True)
            rebase = git_run(["rebase", f"origin/{default}"], repo_path, check=False)
            if rebase.returncode != 0:
                result["blocked_reason"] = "rebase_conflict"
                result["conflicts"] = _conflict_files(repo_path)
                return result
            git_run(["push", "--force-with-lease", "origin", spec_branch], repo_path, check=True)
            result["actions"].append(f"pushed {spec_branch}")

    if story_not_started:
        if not _remote_exists(repo_path, f"origin/{story_branch}"):
            action = f"create {story_branch} from origin/{spec_branch}"
            result["actions"].append(action)
            if not dry_run:
                git_run(["checkout", "-b", story_branch, f"origin/{spec_branch}"], repo_path, check=True)
                git_run(["push", "-u", "origin", story_branch], repo_path, check=True)
                result["actions"].append(f"pushed new {story_branch}")
        elif _spec_is_ahead_of_story(repo_path, spec_branch, story_branch):
            action = f"rebase {story_branch} onto origin/{spec_branch}"
            result["actions"].append(action)
            if not dry_run:
                git_run(["checkout", story_branch], repo_path, check=True)
                rebase = git_run(["rebase", f"origin/{spec_branch}"], repo_path, check=False)
                if rebase.returncode != 0:
                    result["blocked_reason"] = "rebase_conflict"
                    result["conflicts"] = _conflict_files(repo_path)
                    return result
                git_run(["push", "--force-with-lease", "origin", story_branch], repo_path, check=True)
                result["actions"].append(f"pushed {story_branch}")

    if _remote_exists(repo_path, f"origin/{story_branch}"):
        result["post_story_sha"] = _git_output_optional(
            ["rev-parse", f"origin/{story_branch}"],
            repo_path,
        )
        if not dry_run:
            git_run(["fetch", "origin", story_branch], repo_path, check=False)

    for other in other_repos or []:
        other_path = other.get("path")
        if not other_path:
            continue
        result["other_repos"].append(
            sync_other_listed_repo(
                other_path,
                spec_branch,
                story_branch,
                dry_run=dry_run,
            )
        )

    result["status"] = "ok"
    return result
