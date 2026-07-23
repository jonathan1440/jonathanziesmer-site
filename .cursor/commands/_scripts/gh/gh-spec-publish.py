#!/usr/bin/env python3
"""
Publish gh-spec parent + story sub-issues and gh-plan work tasks.

Usage:
  gh-spec-publish.py preflight
  gh-spec-publish.py bootstrap-spec-branch --repo OWNER/REPO --slug SLUG --repo-path PATH [--push]
  gh-spec-publish.py bootstrap-spec-branches --input payload.json [--workspace-root PATH ...] [--push]
  gh-spec-publish.py bootstrap-story-branches --manifest-path PATH [--story US-01] [--push]
  gh-spec-publish.py verify-branches --manifest-path PATH | --input payload.json [--require-story-branches]
  gh-spec-publish.py link-branches --manifest-path PATH [--repo OWNER/REPO]
  gh-spec-publish.py init-spec-artifacts --slug SLUG --title TITLE --repo-path PATH [--repo OWNER/REPO] [--bootstrap] [--push]
  gh-spec-publish.py verify-spec --spec-path PATH [--input publish-payload.json]
  gh-spec-publish.py update-spec --manifest-path PATH --spec-path PATH [--repo-path PATH]
  gh-spec-publish.py finish-spec --repo OWNER/REPO --input payload.json --manifest-path PATH --spec-path PATH
  gh-spec-publish.py publish --repo OWNER/REPO --manifest-path PATH --input payload.json
  gh-spec-publish.py verify --repo OWNER/REPO --manifest-path PATH
  gh-spec-publish.py publish-plan [--manifest-path PATH] --input plan-payload.json
  gh-spec-publish.py finish-plan [--manifest-path PATH] --input plan-payload.json
  gh-spec-publish.py verify-plan --story-repo OWNER/REPO --story-number N [--manifest-path PATH]
  gh-spec-publish.py sync-plan-branches --manifest-path PATH --story-id US-01 --repo-path PATH [--mode plan|update-plan] [--dry-run]
  gh-spec-publish.py check-scope-drift --manifest-path PATH --story-id US-01 --pre-story-sha SHA --post-story-sha SHA [--repo-path PATH] [--other-repo OWNER/REPO:PATH ...] [--no-fetch-issues]
  gh-spec-publish.py render-message --template NAME --input payload.json
  gh-spec-publish.py apply-estimates [--manifest-path PATH] --input estimate-payload.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_COMMANDS_DIR = _SCRIPT_DIR.parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from gh_git_helpers import (
    find_local_repo_path,
    git_run,
    resolve_repo_checkout,
    workspace_roots_from_args,
)
from gh_branch_sync import sync_plan_branches_core
from gh_plan_messages import attach_sync_user_message, render_message
from gh_scope_drift import check_scope_drift_core


GH_HOST = "github.com"
MISSING_SCOPES_PATTERN = re.compile(
    r"missing required scopes\s*\[([^\]]+)\]",
    re.IGNORECASE,
)
ADD_SUB_ISSUE_MUTATION = """
mutation($parentId: ID!, $childId: ID!) {
  addSubIssue(input: { issueId: $parentId, subIssueId: $childId }) {
    issue { number }
    subIssue { number url }
  }
}
"""

ADD_BLOCKED_BY_MUTATION = """
mutation($issueId: ID!, $blockingIssueId: ID!) {
  addBlockedBy(input: { issueId: $issueId, blockingIssueId: $blockingIssueId }) {
    clientMutationId
  }
}
"""

REPOSITORY_NODE_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    id
  }
}
"""

STORY_NOTES_MARKER = "## Implementation notes"

DURATION_PATTERN = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|d|day|days|m|min|mins|minute|minutes)?\s*$",
    re.IGNORECASE,
)

_ESTIMATE_FIELD_CACHE: dict[tuple[str, int], str | None] = {}
_ORG_ISSUE_ESTIMATE_FIELD_CACHE: dict[str, str | None] = {}

ISSUE_URL_PATTERN = re.compile(
    r"^https://github\.com/([^/]+)/([^/]+)/issues/(\d+)/?$"
)

ORG_ISSUE_ESTIMATE_FIELD_QUERY = """
query($owner: String!) {
  organization(login: $owner) {
    issueFields(first: 50) {
      nodes {
        ... on IssueFieldNumber {
          id
          name
        }
      }
    }
  }
}
"""

SUB_ISSUES_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      state
      subIssues(first: 100) { nodes { number title } }
    }
  }
}
"""

PREFLIGHT_QUERY = """
query {
  __type(name: "Mutation") {
    fields { name }
  }
}
"""

ORG_ISSUE_TYPES_QUERY = """
query($owner: String!) {
  organization(login: $owner) {
    issueTypes(first: 100) {
      nodes { id name }
    }
  }
}
"""

UPDATE_ISSUE_ISSUE_TYPE_MUTATION = """
mutation($issueId: ID!, $issueTypeId: ID!) {
  updateIssueIssueType(input: { issueId: $issueId, issueTypeId: $issueTypeId }) {
    issue { number issueType { name } }
  }
}
"""

_ISSUE_TYPE_CREATE_CLI_SUPPORTED: bool | None = None
_ISSUE_TYPE_EDIT_CLI_SUPPORTED: bool | None = None
_ORG_ISSUE_TYPE_IDS: dict[tuple[str, str], str] = {}


@dataclass
class IssueRef:
    number: int
    node_id: str
    url: str
    state: str = "OPEN"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_repo(repo: str) -> tuple[str, str]:
    if "/" not in repo:
        raise ValueError(f"repo must be OWNER/NAME, got: {repo}")
    owner, name = repo.split("/", 1)
    return owner, name


def parse_issue_url(url: str) -> tuple[str, int] | None:
    match = ISSUE_URL_PATTERN.match(url.strip())
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}", int(match.group(3))


STORY_TITLE_ARTICLE_PREFIXES = ("a ", "an ", "the ")

LEGACY_HIERARCHY_LABELS = frozenset({"spec", "user-story", "task"})
DEFAULT_ISSUE_TYPES = {
    "parent": "Spec",
    "story": "User Story",
    "work": "Task",
}


def normalize_issue_hierarchy_payload(payload: dict[str, Any]) -> None:
    """Ensure GitHub issue types are set; strip legacy hierarchy labels from payload."""
    merged = dict(DEFAULT_ISSUE_TYPES)
    if payload.get("types"):
        merged.update(payload["types"])
    payload["types"] = merged

    labels = payload.pop("labels", None)
    if not labels:
        return

    stripped: list[str] = []
    for layer in ("parent", "story", "work"):
        for label in labels.get(layer) or []:
            if label in LEGACY_HIERARCHY_LABELS:
                stripped.append(label)
    if stripped:
        print(
            "gh-spec-publish: stripped legacy hierarchy labels "
            f"{sorted(set(stripped))}; using issue types {payload['types']}",
            file=sys.stderr,
        )


def uses_issue_types(payload: dict[str, Any]) -> bool:
    normalize_issue_hierarchy_payload(payload)
    return bool(payload.get("types"))


def issue_type_for_layer(payload: dict[str, Any], layer: str) -> str | None:
    if not uses_issue_types(payload):
        return None
    types = payload.get("types") or {}
    return types.get(layer) or DEFAULT_ISSUE_TYPES.get(layer)


def labels_for_layer(payload: dict[str, Any], layer: str) -> list[str]:
    """Hierarchy issues use GitHub issue types only — never spec/user-story/task labels."""
    normalize_issue_hierarchy_payload(payload)
    return []


def ensure_issue_type(repo: str, number: int, issue_type: str | None) -> None:
    if not issue_type or number <= 0:
        return
    if cli_issue_edit_supports_type():
        try:
            gh_run(
                [
                    "issue",
                    "edit",
                    str(number),
                    "--repo",
                    repo,
                    "--type",
                    issue_type,
                ]
            )
            return
        except subprocess.CalledProcessError:
            pass
    try:
        set_issue_type_graphql(repo, number, issue_type)
    except (subprocess.CalledProcessError, SystemExit) as exc:
        print(
            f"gh-spec-publish: warn: could not set issue type {issue_type!r} "
            f"on {repo}#{number} ({exc}). "
            "Org issue types require setup_org_projects.py (Team/Enterprise); "
            "do not substitute type:* labels.",
            file=sys.stderr,
        )


def strip_legacy_hierarchy_labels(repo: str, number: int) -> None:
    if number <= 0:
        return
    for label in sorted(LEGACY_HIERARCHY_LABELS):
        try:
            gh_run(
                [
                    "issue",
                    "edit",
                    str(number),
                    "--repo",
                    repo,
                    "--remove-label",
                    label,
                ]
            )
        except subprocess.CalledProcessError:
            continue


def ensure_hierarchy_issue_classification(
    repo: str,
    number: int,
    issue_type: str | None,
    *,
    strip_legacy_labels: bool = True,
) -> None:
    ensure_issue_type(repo, number, issue_type)
    if strip_legacy_labels and issue_type:
        strip_legacy_hierarchy_labels(repo, number)


def slugify_story_title(title: str, max_len: int = 40) -> str:
    normalized = title.lower().strip()
    for prefix in STORY_TITLE_ARTICLE_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "story"


def spec_branch_name(feature_slug: str) -> str:
    return f"spec/{feature_slug}"


def story_branch_name(story_id: str, title: str) -> str:
    return f"user-story/{story_id}-{slugify_story_title(title)}"


def story_id_from_task_id(task_id: str) -> str | None:
    match = re.match(r"^(US-\d+)", task_id)
    return match.group(1) if match else None


def task_branch_name(task_id: str, title: str) -> str:
    story_id = story_id_from_task_id(task_id) or "US-00"
    return f"task/{story_id}-{slugify_story_title(title)}"


def remote_branch_exists(repo: str, branch: str) -> bool:
    owner, name = parse_repo(repo)
    result = _run_gh(
        [
            "api",
            f"repos/{owner}/{name}/git/matching-refs/heads/{branch}",
            "--jq",
            "length",
        ]
    )
    if result.returncode != 0:
        return False
    try:
        return int((result.stdout or "").strip() or "0") > 0
    except ValueError:
        return False


def resolve_task_branch_base(
    task_repo: str,
    manifest: dict[str, Any],
    story_id: str | None,
) -> str:
    stories = manifest.get("stories") or {}
    story_entry = stories.get(story_id or "", {})
    story_branch = story_entry.get("branch")
    spec_branch = manifest.get("spec_branch")
    if story_branch and remote_branch_exists(task_repo, story_branch):
        return story_branch
    if spec_branch and remote_branch_exists(task_repo, spec_branch):
        return spec_branch
    return default_branch(task_repo)


def default_branch(repo: str) -> str:
    data = gh_json(["repo", "view", repo, "--json", "defaultBranchRef"])
    name = (data.get("defaultBranchRef") or {}).get("name")
    if not name:
        raise SystemExit(f"could not resolve default branch for {repo}")
    return name


def linked_branches_supported() -> bool:
    return "createLinkedBranch" in mutation_fields()


def linked_branches(repo: str, issue_number: int) -> set[str]:
    result = _gh_with_auth_retry(
        ["issue", "develop", "--list", str(issue_number), "--repo", repo]
    )
    if result.returncode != 0:
        return set()
    names: set[str] = set()
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        name = line.split("\t", 1)[0].strip()
        if name:
            names.add(name)
    return names


@dataclass
class StoryRepo:
    name: str
    role: str | None = None


def parse_story_repos(story: dict[str, Any], home_repo: str) -> list[StoryRepo]:
    """Normalize repos touched by a story from publish payload."""
    raw = story.get("repos")
    parsed: list[StoryRepo] = []
    if raw:
        for item in raw:
            if isinstance(item, str):
                name = item.strip()
                if name:
                    parsed.append(StoryRepo(name=name))
            elif isinstance(item, dict):
                name = (item.get("repo") or item.get("name") or "").strip()
                if name:
                    role = item.get("role")
                    parsed.append(
                        StoryRepo(name=name, role=str(role).strip() if role else None)
                    )
    if not parsed:
        print(
            f"gh-spec: story {story.get('id', '?')} missing repos — defaulting to home repo {home_repo}",
            file=sys.stderr,
        )
        parsed = [StoryRepo(name=home_repo)]
    deduped: list[StoryRepo] = []
    seen: set[str] = set()
    for repo in parsed:
        if "/" not in repo.name:
            raise SystemExit(f"invalid repo (expected OWNER/NAME): {repo.name!r}")
        if repo.name in seen:
            continue
        seen.add(repo.name)
        deduped.append(repo)
    return deduped


def repos_for_manifest(repos: list[StoryRepo]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for repo in repos:
        entry: dict[str, str] = {"repo": repo.name}
        if repo.role:
            entry["role"] = repo.role
        out.append(entry)
    return out


def format_repos_index(repos: list[StoryRepo]) -> str:
    parts: list[str] = []
    for repo in repos:
        short = repo.name.split("/", 1)[-1]
        parts.append(short)
    return ", ".join(parts)


def union_affected_repos(payload: dict[str, Any], home_repo: str) -> list[StoryRepo]:
    """Deduped union of parent payload repos or all per-story repos (always includes home)."""
    parent_raw = payload.get("repos")
    if parent_raw:
        return parse_story_repos({"repos": parent_raw}, home_repo)
    merged: list[StoryRepo] = []
    seen: set[str] = set()
    for candidate in [StoryRepo(name=home_repo), *(
        repo
        for story in payload.get("stories", [])
        for repo in parse_story_repos(story, home_repo)
    )]:
        if candidate.name in seen:
            continue
        seen.add(candidate.name)
        merged.append(candidate)
    return merged


def render_affected_repos_section(repos: list[StoryRepo]) -> str:
    lines = [
        "## Affected repositories",
        "",
        "| Repository | Role |",
        "|------------|------|",
    ]
    for repo in repos:
        role = repo.role or "—"
        lines.append(f"| `{repo.name}` | {role} |")
    return "\n".join(lines)


def render_dev_branches_section(
    repos: list[StoryRepo],
    branch_name: str,
    home_repo: str,
) -> str:
    lines = [
        "## Development branches",
        "",
        "Create each branch in every repository listed (same branch name). "
        f"Link to this issue via `gh issue develop` in `{home_repo}` only.",
        "",
        "| Repository | Branch | Issue link |",
        "|------------|--------|------------|",
    ]
    for repo in repos:
        link = "Yes" if repo.name == home_repo else "Branch only"
        lines.append(f"| `{repo.name}` | `{branch_name}` | {link} |")
    return "\n".join(lines)


def render_repos_section(repos: list[StoryRepo], home_repo: str) -> str:
    lines = [
        "## Repositories touched",
        "",
        "| Repository | Role |",
        "|------------|------|",
    ]
    for repo in repos:
        role = repo.role or "—"
        lines.append(f"| `{repo.name}` | {role} |")
    lines.extend(
        [
            "",
            f"_Story issue home repo: `{home_repo}` (this issue). Implementation may span the repositories above._",
        ]
    )
    return "\n".join(lines)


def story_repos_from_manifest(entry: dict[str, Any], home_repo: str) -> list[StoryRepo]:
    raw = entry.get("repos")
    if not raw:
        return [StoryRepo(name=home_repo)]
    return parse_story_repos({"repos": raw}, home_repo=home_repo)


def link_issue_branch(
    repo: str,
    issue_number: int,
    name: str,
    base: str,
    *,
    enabled: bool = True,
) -> None:
    if not enabled or issue_number <= 0:
        return
    if name in linked_branches(repo, issue_number):
        return
    try:
        gh_run(
            [
                "issue",
                "develop",
                str(issue_number),
                "--repo",
                repo,
                "--name",
                name,
                "--base",
                base,
            ]
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"gh-spec-publish: warn: could not link branch {name!r} to "
            f"{repo}#{issue_number} ({exc})",
            file=sys.stderr,
        )


def parse_missing_scopes(stderr: str) -> list[str]:
    match = MISSING_SCOPES_PATTERN.search(stderr or "")
    if not match:
        return []
    return [scope.strip() for scope in match.group(1).split(",") if scope.strip()]


# gh reports "read:project" missing but `gh auth refresh -s` accepts "project".
REFRESH_SCOPE_ALIASES: dict[str, str] = {
    "read:project": "project",
}


def scopes_for_auth_refresh(reported_scopes: list[str]) -> list[str]:
    """Map gh-reported missing scopes to `gh auth refresh -s` arguments (deduped)."""
    refresh: list[str] = []
    for scope in reported_scopes:
        mapped = REFRESH_SCOPE_ALIASES.get(scope, scope)
        if mapped not in refresh:
            refresh.append(mapped)
    return refresh


def gh_auth_refresh(reported_scopes: list[str]) -> None:
    scopes = scopes_for_auth_refresh(reported_scopes)
    if not scopes:
        return
    reported_list = ", ".join(reported_scopes)
    refresh_list = ", ".join(scopes)
    print(
        f"gh: missing OAuth scope(s) [{reported_list}] — running "
        f"`gh auth refresh -h {GH_HOST} -s {refresh_list}` "
        f"(complete device flow if prompted)",
        file=sys.stderr,
    )
    args = ["gh", "auth", "refresh", "-h", GH_HOST]
    for scope in scopes:
        args.extend(["-s", scope])
    subprocess.run(args, check=False)


def _run_gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
    )


def _gh_with_auth_retry(args: list[str]) -> subprocess.CompletedProcess[str]:
    result = _run_gh(args)
    if result.returncode == 0:
        return result

    stderr = (result.stderr or "") + (result.stdout or "")
    scopes = parse_missing_scopes(stderr)
    if not scopes:
        return result

    gh_auth_refresh(scopes)
    return _run_gh(args)


def gh_json(args: list[str]) -> Any:
    result = _gh_with_auth_retry(args)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            ["gh", *args],
            output=result.stdout,
            stderr=result.stderr,
        )
    return json.loads(result.stdout)


def gh_run(args: list[str]) -> str:
    result = _gh_with_auth_retry(args)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            ["gh", *args],
            output=result.stdout,
            stderr=result.stderr,
        )
    return result.stdout.strip()


def ensure_project_auth(payload: dict[str, Any]) -> None:
    """Probe project API when a project is configured; refresh scopes before publish."""
    project = payload.get("project") or {}
    if not project.get("title") and not project.get("number"):
        return

    owner = project.get("owner")
    if not owner:
        owner = parse_repo(payload["repo"])[0]

    probe = _run_gh(["project", "list", "--owner", owner, "--limit", "1"])
    if probe.returncode == 0:
        return

    stderr = (probe.stderr or "") + (probe.stdout or "")
    scopes = parse_missing_scopes(stderr)
    if scopes:
        gh_auth_refresh(scopes)
        return

    if "read:project" in stderr.lower() or "project" in stderr.lower():
        gh_auth_refresh(["read:project"])


def graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    return graphql_with_features(query, variables)


def graphql_with_features(
    query: str,
    variables: dict[str, Any] | None = None,
    *,
    features: str | None = None,
) -> dict[str, Any]:
    cmd = ["api", "graphql", "-f", f"query={query}"]
    if features:
        cmd.extend(["-H", f"GraphQL-Features:{features}"])
    if variables:
        for key, value in variables.items():
            if isinstance(value, bool):
                cmd.extend(["-F", f"{key}={str(value).lower()}"])
            elif isinstance(value, int):
                cmd.extend(["-F", f"{key}={value}"])
            elif isinstance(value, (dict, list)):
                cmd.extend(["-f", f"{key}={json.dumps(value)}"])
            else:
                cmd.extend(["-f", f"{key}={value}"])
    return gh_json(cmd)


def _gh_subcommand_supports_flag(subcommand: str, flag: str) -> bool:
    result = _run_gh(["issue", subcommand, "--help"])
    help_text = (result.stdout or "") + (result.stderr or "")
    return flag in help_text


def cli_issue_create_supports_type() -> bool:
    global _ISSUE_TYPE_CREATE_CLI_SUPPORTED
    if _ISSUE_TYPE_CREATE_CLI_SUPPORTED is None:
        _ISSUE_TYPE_CREATE_CLI_SUPPORTED = _gh_subcommand_supports_flag(
            "create", "--type"
        )
    return _ISSUE_TYPE_CREATE_CLI_SUPPORTED


def cli_issue_edit_supports_type() -> bool:
    global _ISSUE_TYPE_EDIT_CLI_SUPPORTED
    if _ISSUE_TYPE_EDIT_CLI_SUPPORTED is None:
        _ISSUE_TYPE_EDIT_CLI_SUPPORTED = _gh_subcommand_supports_flag("edit", "--type")
    return _ISSUE_TYPE_EDIT_CLI_SUPPORTED


def cli_supports_issue_type_flags() -> bool:
    """Backward-compatible alias: gh issue create exposes --type."""
    return cli_issue_create_supports_type()


def resolve_org_issue_type_id(org: str, type_name: str) -> str:
    key = (org, type_name.strip().lower())
    if key in _ORG_ISSUE_TYPE_IDS:
        return _ORG_ISSUE_TYPE_IDS[key]

    data = graphql_with_features(
        ORG_ISSUE_TYPES_QUERY,
        {"owner": org},
        features="issue_types",
    )
    nodes = (
        data.get("data", {})
        .get("organization", {})
        .get("issueTypes", {})
        .get("nodes", [])
    )
    for node in nodes:
        name = (node.get("name") or "").strip()
        node_id = node.get("id")
        if name and node_id:
            _ORG_ISSUE_TYPE_IDS[(org, name.lower())] = node_id

    type_id = _ORG_ISSUE_TYPE_IDS.get(key)
    if not type_id:
        available = ", ".join(
            sorted({(n.get("name") or "") for n in nodes if n.get("name")})
        )
        raise SystemExit(
            f"issue type {type_name!r} not found for org {org}. "
            f"Available: {available or '(none)'}"
        )
    return type_id


def set_issue_type_graphql(repo: str, number: int, issue_type: str) -> None:
    owner, _ = parse_repo(repo)
    ref = issue_ref(repo, number)
    type_id = resolve_org_issue_type_id(owner, issue_type)
    graphql_with_features(
        UPDATE_ISSUE_ISSUE_TYPE_MUTATION,
        {"issueId": ref.node_id, "issueTypeId": type_id},
        features="issue_types",
    )


def mutation_fields() -> set[str]:
    data = graphql(PREFLIGHT_QUERY)
    fields = data.get("data", {}).get("__type", {}).get("fields", [])
    return {f.get("name", "") for f in fields}


def sub_issues_supported() -> bool:
    return "addSubIssue" in mutation_fields()


def blocked_by_supported() -> bool:
    return "addBlockedBy" in mutation_fields()


def repository_node_id(repo: str) -> str:
    owner, name = parse_repo(repo)
    data = graphql(REPOSITORY_NODE_QUERY, {"owner": owner, "name": name})
    node_id = data.get("data", {}).get("repository", {}).get("id")
    if not node_id:
        raise SystemExit(f"repository not found: {repo}")
    return node_id


def add_blocked_by(blocked_id: str, blocking_id: str) -> None:
    graphql(
        ADD_BLOCKED_BY_MUTATION,
        {"issueId": blocked_id, "blockingIssueId": blocking_id},
    )


def project_item_add(owner: str, project_number: int, issue_url: str) -> None:
    gh_run(
        [
            "project",
            "item-add",
            str(project_number),
            "--owner",
            owner,
            "--url",
            issue_url,
        ]
    )


def parse_duration_hours(raw: str | None) -> float | None:
    """Parse duration_estimate (e.g. 3h, 0.5d) to hours for project Estimate field."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    match = DURATION_PATTERN.match(text)
    if not match:
        try:
            return float(text)
        except ValueError:
            return None
    value = float(match.group(1))
    unit = (match.group(2) or "h").lower()
    if unit in ("h", "hr", "hrs", "hour", "hours"):
        return value
    if unit in ("d", "day", "days"):
        return value * 8.0
    if unit in ("m", "min", "mins", "minute", "minutes"):
        return value / 60.0
    return value


def resolve_project_config(
    manifest: dict[str, Any],
    payload: dict[str, Any],
    *,
    default_owner: str | None = None,
) -> dict[str, Any] | None:
    """Resolve project owner, number, and GraphQL id from manifest or payload."""
    project = dict(manifest.get("project") or payload.get("project") or {})
    if not project.get("title") and not project.get("number"):
        return None

    owner = project.get("owner") or default_owner
    if not owner:
        repo = payload.get("repo") or manifest.get("repo")
        if repo:
            owner = parse_repo(repo)[0]
    if not owner:
        return None

    if project.get("number"):
        number = int(project["number"])
        if project.get("id"):
            return {
                "owner": owner,
                "number": number,
                "id": project["id"],
                "title": project.get("title"),
            }
        data = gh_json(
            ["project", "view", str(number), "--owner", owner, "--format", "json"]
        )
        return {
            "owner": owner,
            "number": number,
            "id": data["id"],
            "title": data.get("title") or project.get("title"),
        }

    title = project.get("title")
    if not title:
        return None

    data = gh_json(
        ["project", "list", "--owner", owner, "--format", "json", "--limit", "100"]
    )
    for entry in data.get("projects", []):
        if entry.get("title") == title:
            return {
                "owner": owner,
                "number": int(entry["number"]),
                "id": entry["id"],
                "title": title,
            }
    return None


def get_estimate_field_id(owner: str, project_number: int) -> str | None:
    cache_key = (owner, project_number)
    if cache_key not in _ESTIMATE_FIELD_CACHE:
        data = gh_json(
            [
                "project",
                "field-list",
                str(project_number),
                "--owner",
                owner,
                "--format",
                "json",
            ]
        )
        field_id: str | None = None
        for field in data.get("fields", []):
            if field.get("name") == "Estimate":
                field_id = field.get("id")
                break
        if not field_id:
            for field in data.get("fields", []):
                if field.get("name") == "Estimation":
                    field_id = field.get("id")
                    break
        _ESTIMATE_FIELD_CACHE[cache_key] = field_id
    return _ESTIMATE_FIELD_CACHE[cache_key]


def find_project_item_id(
    owner: str,
    project_number: int,
    issue_url: str,
) -> str | None:
    cursor: str | None = None
    while True:
        args = [
            "project",
            "item-list",
            str(project_number),
            "--owner",
            owner,
            "--format",
            "json",
            "--limit",
            "100",
        ]
        if cursor:
            args.extend(["--after", cursor])
        data = gh_json(args)
        for item in data.get("items", []):
            content = item.get("content") or {}
            if content.get("url") == issue_url:
                return item.get("id")
        page = data.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
    return None


def get_org_issue_estimate_field_id(org_login: str) -> str | None:
    if org_login not in _ORG_ISSUE_ESTIMATE_FIELD_CACHE:
        try:
            data = graphql(
                ORG_ISSUE_ESTIMATE_FIELD_QUERY,
                {"owner": org_login},
            )
        except subprocess.CalledProcessError:
            _ORG_ISSUE_ESTIMATE_FIELD_CACHE[org_login] = None
            return None
        field_id: str | None = None
        nodes = (
            data.get("data", {})
            .get("organization", {})
            .get("issueFields", {})
            .get("nodes", [])
        )
        for node in nodes:
            if node.get("name") == "Estimate":
                field_id = node.get("id")
                break
        _ORG_ISSUE_ESTIMATE_FIELD_CACHE[org_login] = field_id
    return _ORG_ISSUE_ESTIMATE_FIELD_CACHE[org_login]


def get_issue_node_id(repo: str, issue_number: int) -> str | None:
    data = gh_json(
        [
            "issue",
            "view",
            str(issue_number),
            "--repo",
            repo,
            "--json",
            "id",
        ]
    )
    return data.get("id")


def set_issue_estimate_field(
    org_login: str,
    repo: str,
    issue_number: int,
    hours: float,
) -> None:
    field_id = get_org_issue_estimate_field_id(org_login)
    if not field_id:
        raise RuntimeError(
            f"organization {org_login} has no org-level Estimate issue field"
        )
    issue_id = get_issue_node_id(repo, issue_number)
    if not issue_id:
        raise RuntimeError(f"could not resolve node id for {repo}#{issue_number}")
    # Inline numberValue: gh api graphql cannot pass Float variables reliably.
    mutation = f"""
mutation {{
  updateIssueFieldValue(
    input: {{
      issueId: "{issue_id}"
      issueField: {{ fieldId: "{field_id}", numberValue: {hours:g} }}
    }}
  ) {{
    issue {{ number }}
  }}
}}
"""
    graphql(mutation)


def set_project_item_estimate(
    org_login: str,
    repo: str,
    issue_number: int,
    hours: float,
) -> None:
    """Set org-level Estimate issue field (syncs to project views)."""
    set_issue_estimate_field(org_login, repo, issue_number, hours)


def ensure_project_estimate(
    project: dict[str, Any],
    issue_url: str,
    duration_estimate: str | None,
    *,
    dry_run: bool,
) -> None:
    """Set GitHub Project Estimate field from duration_estimate when configured."""
    hours = parse_duration_hours(duration_estimate)
    if hours is None or dry_run or not issue_url:
        return

    owner = project.get("owner")
    number = project.get("number")
    project_id = project.get("id")
    if not owner or not number or not project_id:
        return

    if not get_org_issue_estimate_field_id(owner):
        print(
            "warn: organization has no Estimate issue field; skipped duration_estimate",
            file=sys.stderr,
        )
        return

    parsed = parse_issue_url(issue_url)
    if not parsed:
        print(
            f"warn: could not parse issue URL for Estimate field: {issue_url}",
            file=sys.stderr,
        )
        return
    repo, issue_number = parsed

    try:
        set_issue_estimate_field(owner, repo, issue_number, hours)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"warn: Estimate field update failed: {exc}", file=sys.stderr)


def issue_body(repo: str, number: int) -> str:
    data = gh_json(
        ["issue", "view", str(number), "--repo", repo, "--json", "body,title"]
    )
    return data.get("body") or ""


def append_story_notes_replace(body: str, notes: str) -> str:
    block = f"{STORY_NOTES_MARKER}\n\n{notes.strip()}\n"
    if STORY_NOTES_MARKER in body:
        pattern = re.compile(
            rf"{re.escape(STORY_NOTES_MARKER)}.*?(?=\n## |\Z)",
            re.DOTALL,
        )
        return pattern.sub(block.rstrip() + "\n", body)
    return body.rstrip() + "\n\n" + block


def append_story_notes(repo: str, number: int, notes: str) -> None:
    if not notes.strip():
        return
    body = append_story_notes_replace(issue_body(repo, number), notes)
    data = gh_json(
        ["issue", "view", str(number), "--repo", repo, "--json", "title"]
    )
    edit_issue(repo, number, data["title"], body)


def issue_ref(repo: str, number: int) -> IssueRef:
    data = gh_json(
        [
            "issue",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "id,number,url,state",
        ]
    )
    return IssueRef(
        number=int(data["number"]),
        node_id=data["id"],
        url=data["url"],
        state=data.get("state", "OPEN"),
    )


def create_issue(
    repo: str,
    title: str,
    body: str,
    labels: list[str],
    project_title: str | None,
    issue_type: str | None = None,
) -> IssueRef:
    args = [
        "issue",
        "create",
        "--repo",
        repo,
        "--title",
        title,
        "--body",
        body,
    ]
    if issue_type and cli_issue_create_supports_type():
        args.extend(["--type", issue_type])
    elif not issue_type:
        for label in labels:
            args.extend(["--label", label])
    if project_title:
        args.extend(["--project", project_title])
    url = gh_run(args)
    number = int(url.rstrip("/").split("/")[-1])
    ref = issue_ref(repo, number)
    if issue_type:
        ensure_issue_type(repo, number, issue_type)
    return ref


def create_issue_resilient(
    repo: str,
    title: str,
    body: str,
    labels: list[str],
    project_title: str | None,
    manifest: dict[str, Any],
    issue_type: str | None = None,
) -> IssueRef:
    """Create issue; retry without project, then item-add. Prefer --type over labels."""
    attempts: list[tuple[list[str], str | None]] = [
        (labels, project_title),
        (labels, None),
    ]
    if not issue_type:
        attempts.append(([], None))
    last_error: subprocess.CalledProcessError | None = None
    for attempt_labels, attempt_project in attempts:
        try:
            ref = create_issue(
                repo,
                title,
                body,
                attempt_labels,
                attempt_project,
                issue_type=issue_type,
            )
            if not attempt_project and project_title:
                ensure_project_item(manifest, ref.url, dry_run=False)
            elif attempt_project and manifest.get("project", {}).get("number"):
                ensure_project_item(manifest, ref.url, dry_run=False)
            return ref
        except subprocess.CalledProcessError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise SystemExit("create_issue_resilient: no attempts made")


def edit_issue(repo: str, number: int, title: str, body: str) -> None:
    gh_run(
        [
            "issue",
            "edit",
            str(number),
            "--repo",
            repo,
            "--title",
            title,
            "--body",
            body,
        ]
    )


def add_sub_issue(parent_id: str, child_id: str) -> None:
    graphql(
        ADD_SUB_ISSUE_MUTATION,
        {"parentId": parent_id, "childId": child_id},
    )


def list_sub_issue_numbers(repo: str, parent_number: int) -> set[int]:
    owner, name = parse_repo(repo)
    data = graphql(
        SUB_ISSUES_QUERY,
        {"owner": owner, "name": name, "number": parent_number},
    )
    nodes = (
        data.get("data", {})
        .get("repository", {})
        .get("issue", {})
        .get("subIssues", {})
        .get("nodes", [])
    )
    return {int(n["number"]) for n in nodes}


def render_story_body(
    story_line: str,
    scenarios: list[dict[str, Any]],
    parent_number: int,
    spec_path: str,
    branch: str | None = None,
    repos: list[StoryRepo] | None = None,
    home_repo: str | None = None,
) -> str:
    lines = [
        "## User story",
        "",
        story_line,
        "",
    ]
    if repos and home_repo:
        lines.extend([render_repos_section(repos, home_repo), "", "## Acceptance scenarios", ""])
    else:
        lines.extend(["## Acceptance scenarios", ""])
    for scenario in scenarios:
        lines.extend(
            [
                f"### {scenario['id']} — {scenario['name']}",
                f"- **Given** {scenario['given']}",
                f"- **When** {scenario['when']}",
                f"- **Then** {scenario['then']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Links",
            "",
            f"- Parent spec: #{parent_number}",
            f"- Spec file: `{spec_path}`",
        ]
    )
    if branch and repos and home_repo:
        lines.extend(["", render_dev_branches_section(repos, branch, home_repo)])
    elif branch:
        lines.extend(["", "## Development branch", "", f"`{branch}`"])
    return "\n".join(lines)


def render_parent_body(
    payload: dict[str, Any],
    parent_number: int,
    stories_manifest: dict[str, Any],
) -> str:
    slug = payload["feature_slug"]
    spec_path = payload["spec_path"]
    branch = payload.get("branch", "main")
    objective = payload.get("parent", {}).get("objective_summary", "")
    home_repo = payload["repo"]
    affected_repos = union_affected_repos(payload, home_repo)

    rows = ["| Story | Issue | Repositories | AC IDs |", "|-------|-------|--------------|--------|"]
    for story in payload.get("stories", []):
        story_id = story["id"]
        entry = stories_manifest.get(story_id, {})
        issue_num = entry.get("number", "TBD")
        repos_label = format_repos_index(
            story_repos_from_manifest(entry, payload["repo"])
            if entry.get("repos")
            else parse_story_repos(story, payload["repo"])
        )
        ac_ids = ", ".join(s["id"] for s in story.get("acceptance_scenarios", []))
        rows.append(f"| {story_id} | #{issue_num} | {repos_label} | {ac_ids} |")

    sections = [
        "## Spec artifact",
        "",
        f"`{spec_path}` on branch `{branch}`",
        "",
        f"Manifest: `docs/specs/{slug}/gh-spec.manifest.json`",
        "",
        render_affected_repos_section(affected_repos),
        "",
        render_dev_branches_section(affected_repos, branch, home_repo),
        "",
        "## Objective",
        "",
        objective,
        "",
        "## Status",
        "",
        "- [x] Stories approved",
        "- [x] Acceptance criteria approved",
        "- [x] Technical spec approved",
        "- [ ] Tasks published (`/gh-plan` per story)",
        "",
        "## Story index",
        "",
        *rows,
        "",
        "## Traceability",
        "",
        "- **Canonical AC:** story sub-issues below (not duplicated in `SPEC.md`).",
        "- **Work units:** `/gh-plan` per story creates task sub-issues (scope, tests, blockers).",
        "",
        f"_Parent issue #{parent_number}_",
    ]
    return "\n".join(sections)


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = utc_now_iso()
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def ensure_open_issue(repo: str, number: int, context: str) -> IssueRef:
    ref = issue_ref(repo, number)
    if ref.state != "OPEN":
        raise SystemExit(
            f"{context} issue #{number} is {ref.state}. "
            "Reopen, create a new parent, or edit manifest before re-publishing."
        )
    return ref


def publish_stories(
    repo: str,
    payload: dict[str, Any],
    manifest: dict[str, Any],
    parent: IssueRef,
    *,
    spec_branch: str,
    link_branches: bool,
    dry_run: bool = False,
) -> dict[str, Any]:
    stories_manifest = dict(manifest.get("stories", {}))
    story_labels = labels_for_layer(payload, "story")
    story_issue_type = issue_type_for_layer(payload, "story")
    hierarchy = manifest.get("hierarchy", "sub_issues")
    spec_path = payload["spec_path"]

    for story in payload.get("stories", []):
        story_id = story["id"]
        story_repos = parse_story_repos(story, repo)
        story_branch = story_branch_name(story_id, story["title"])
        title = f"{story_id}: {story['title']}"
        body = render_story_body(
            story["story_line"],
            story.get("acceptance_scenarios", []),
            parent.number,
            spec_path,
            branch=story_branch,
            repos=story_repos,
            home_repo=repo,
        )

        existing = stories_manifest.get(story_id)
        if existing and existing.get("number"):
            ref = ensure_open_issue(repo, int(existing["number"]), story_id)
            if not dry_run:
                edit_issue(repo, ref.number, title, body)
                ensure_hierarchy_issue_classification(
                    repo, ref.number, story_issue_type
                )
        else:
            if dry_run:
                ref = IssueRef(number=0, node_id="DRY_RUN", url="")
            else:
                flat_body = body
                if hierarchy == "flat":
                    flat_body = body + "\n\n---\n\n" + f"Parent: #{parent.number}"
                ref = create_issue(
                    repo,
                    title,
                    flat_body,
                    story_labels,
                    payload.get("project", {}).get("title"),
                    issue_type=story_issue_type,
                )
                if hierarchy != "flat":
                    add_sub_issue(parent.node_id, ref.node_id)
                ensure_hierarchy_issue_classification(
                    repo, ref.number, story_issue_type
                )

        if not dry_run and ref.number:
            link_issue_branch(
                repo,
                ref.number,
                story_branch,
                spec_branch,
                enabled=link_branches,
            )

        ac_ids = [s["id"] for s in story.get("acceptance_scenarios", [])]
        stories_manifest[story_id] = {
            "number": ref.number,
            "node_id": ref.node_id,
            "url": ref.url,
            "ac_ids": ac_ids,
            "branch": story_branch,
            "repos": repos_for_manifest(story_repos),
        }

    return stories_manifest


def cmd_preflight(_: argparse.Namespace) -> int:
    fields = mutation_fields()
    sub_ok = "addSubIssue" in fields
    block_ok = "addBlockedBy" in fields
    linked_ok = "createLinkedBranch" in fields
    print(f"sub_issues: {'supported' if sub_ok else 'unavailable'}")
    print(f"blocked_by: {'supported' if block_ok else 'unavailable'}")
    print(f"linked_branches: {'supported' if linked_ok else 'unavailable'}")
    if sub_ok and block_ok:
        return 0
    if not sub_ok:
        print("Use flat fallback for sub-issues (see gh-spec-github-procedure.md)")
    return 1


def cmd_publish(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    normalize_issue_hierarchy_payload(payload)
    manifest_path = Path(args.manifest_path)
    manifest = load_manifest(manifest_path)
    repo = args.repo or payload["repo"]

    spec_branch = spec_branch_name(payload["feature_slug"])
    payload["branch"] = spec_branch
    affected_repos = union_affected_repos(payload, repo)
    link_branches = linked_branches_supported()

    if not args.dry_run:
        ensure_project_auth(payload)

    hierarchy = "sub_issues" if sub_issues_supported() else "flat"
    if args.dry_run:
        hierarchy = manifest.get("hierarchy", hierarchy)

    parent_entry = manifest.get("parent_issue") or {}
    parent_labels = labels_for_layer(payload, "parent")
    parent_issue_type = issue_type_for_layer(payload, "parent")
    project_title = payload.get("project", {}).get("title")

    if parent_entry.get("number"):
        parent = ensure_open_issue(repo, int(parent_entry["number"]), "Parent")
        if not args.dry_run:
            ensure_hierarchy_issue_classification(
                repo, parent.number, parent_issue_type
            )
    else:
        placeholder_body = render_parent_body(payload, 0, {})
        if args.dry_run:
            parent = IssueRef(number=0, node_id="DRY_RUN", url="")
        else:
            parent = create_issue(
                repo,
                f"Spec: {payload['feature_title']}",
                placeholder_body,
                parent_labels,
                project_title,
                issue_type=parent_issue_type,
            )
            ensure_hierarchy_issue_classification(
                repo, parent.number, parent_issue_type
            )

    if not args.dry_run and parent.number and link_branches:
        base = default_branch(repo)
        link_issue_branch(repo, parent.number, spec_branch, base, enabled=True)

    stories_manifest = publish_stories(
        repo,
        payload,
        manifest,
        parent,
        spec_branch=spec_branch,
        link_branches=link_branches,
        dry_run=args.dry_run,
    )

    if not args.dry_run and parent.number:
        parent_body = render_parent_body(payload, parent.number, stories_manifest)
        edit_issue(
            repo,
            parent.number,
            f"Spec: {payload['feature_title']}",
            parent_body,
        )

    out = {
        "schema_version": "v1",
        "feature_slug": payload["feature_slug"],
        "feature_title": payload["feature_title"],
        "repo": repo,
        "spec_path": payload["spec_path"],
        "spec_branch": spec_branch,
        "repos": repos_for_manifest(affected_repos),
        "project": payload.get("project", {}),
        "hierarchy": hierarchy,
        "status": "complete",
        "parent_issue": {
            "number": parent.number,
            "node_id": parent.node_id,
            "url": parent.url,
        },
        "stories": stories_manifest,
        "work_issues": manifest.get("work_issues", {}),
        "issue_types": payload.get("types", dict(DEFAULT_ISSUE_TYPES)),
        "published_at": manifest.get("published_at") or utc_now_iso(),
    }
    if not args.dry_run:
        save_manifest(manifest_path, out)
        print(json.dumps(out, indent=2))
    else:
        print(json.dumps(out, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.manifest_path))
    repo = args.repo or manifest.get("repo")
    if not repo:
        raise SystemExit("repo required")

    parent_number = manifest.get("parent_issue", {}).get("number")
    if not parent_number:
        raise SystemExit("manifest missing parent_issue.number")

    parent = issue_ref(repo, int(parent_number))
    if parent.state != "OPEN":
        raise SystemExit(f"parent issue #{parent_number} is {parent.state}")

    hierarchy = manifest.get("hierarchy", "sub_issues")
    sub_numbers = list_sub_issue_numbers(repo, int(parent_number)) if hierarchy != "flat" else set()

    errors: list[str] = []
    spec_branch = manifest.get("spec_branch")
    if not spec_branch:
        errors.append("manifest missing spec_branch")
    if not manifest.get("repos"):
        errors.append("manifest missing repos (affected repositories)")

    for story_id, entry in manifest.get("stories", {}).items():
        number = entry.get("number")
        if not number:
            errors.append(f"{story_id}: missing issue number in manifest")
            continue
        if not entry.get("branch"):
            errors.append(f"{story_id}: missing branch in manifest")
        if not entry.get("repos"):
            errors.append(f"{story_id}: missing repos in manifest")
        ref = issue_ref(repo, int(number))
        if ref.state != "OPEN":
            errors.append(f"{story_id}: issue #{number} is {ref.state}")
        if hierarchy != "flat" and int(number) not in sub_numbers:
            errors.append(f"{story_id}: issue #{number} is not a sub-issue of #{parent_number}")

    if linked_branches_supported() and spec_branch:
        parent_linked = linked_branches(repo, int(parent_number))
        if spec_branch not in parent_linked:
            errors.append(
                f"parent: issue #{parent_number} not linked to branch {spec_branch!r} "
                "(re-run publish or step 5b manual linking)"
            )
        for story_id, entry in manifest.get("stories", {}).items():
            number = entry.get("number")
            story_branch = entry.get("branch")
            if not number or not story_branch:
                continue
            story_linked = linked_branches(repo, int(number))
            if story_branch not in story_linked:
                errors.append(
                    f"{story_id}: issue #{number} not linked to branch {story_branch!r} "
                    "(re-run publish or step 5b manual linking)"
                )

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1

    print("verify: ok")
    return 0


def cmd_fix_hierarchy_types(args: argparse.Namespace) -> int:
    """Set GitHub issue types and remove legacy spec/user-story/task labels from manifest issues."""
    manifest_path = Path(args.manifest_path)
    manifest = load_manifest(manifest_path)
    repo = args.repo or manifest.get("repo")
    if not repo:
        raise SystemExit("repo required (manifest or --repo)")

    types_cfg = manifest.get("issue_types") or dict(DEFAULT_ISSUE_TYPES)
    parent_number = manifest.get("parent_issue", {}).get("number")
    if not parent_number:
        raise SystemExit("manifest missing parent_issue.number")

    ensure_hierarchy_issue_classification(
        repo, int(parent_number), types_cfg.get("parent")
    )
    for story_id, entry in manifest.get("stories", {}).items():
        number = entry.get("number")
        if not number:
            raise SystemExit(f"manifest story {story_id} missing number")
        ensure_hierarchy_issue_classification(
            repo, int(number), types_cfg.get("story")
        )

    for task_id, entry in manifest.get("work_issues", {}).items():
        number = entry.get("number")
        if not number:
            continue
        task_repo = entry.get("repo") or repo
        ensure_hierarchy_issue_classification(
            task_repo, int(number), types_cfg.get("work")
        )

    print("fix-hierarchy-types: ok")
    return 0


def _format_scope_table(task: dict[str, Any]) -> list[str]:
    files = task.get("files", [])
    if not files:
        return ["_(none listed)_"]
    if isinstance(files, str):
        return [files]
    lines = ["| File | Change |", "|------|--------|"]
    for entry in files:
        if isinstance(entry, str):
            lines.append(f"| `{entry}` | |")
        else:
            lines.append(f"| `{entry.get('path', '')}` | {entry.get('change', '')} |")
    return lines


def _format_tests(task: dict[str, Any]) -> list[str]:
    tests = task.get("tests") or {}
    if isinstance(tests, str):
        return [tests]
    lines: list[str] = []
    test_files = tests.get("files") or []
    if test_files:
        lines.append(f"- Add/update: {', '.join(f'`{f}`' for f in test_files)}")
    verify = tests.get("verify") or task.get("verify")
    if verify:
        lines.append(f"- Verify: `{verify}`")
    return lines or ["_(none listed)_"]


def _format_blockers(blocker_refs: list[dict[str, Any]]) -> list[str]:
    if not blocker_refs:
        return ["- Blocked by: none"]
    lines = []
    for ref in blocker_refs:
        repo = ref.get("repo", "")
        number = ref.get("number", "")
        kind = ref.get("kind", "issue")
        extra = ""
        if ref.get("task_id"):
            extra = f" ({ref['task_id']})"
        if ref.get("reason"):
            extra += f" — {ref['reason']}"
        lines.append(f"- Blocked by: {repo}#{number}{extra} [{kind}]")
    return lines


def render_work_body_v2(
    task: dict[str, Any],
    story_issue: dict[str, Any],
    spec_path: str | None,
    blocker_refs: list[dict[str, Any]] | None = None,
    branch: str | None = None,
) -> str:
    story_id = story_issue.get("id") or f"#{story_issue['number']}"
    story_num = story_issue["number"]
    duration = task.get("duration_estimate", "")
    patterns = task.get("patterns") or []
    decisions = task.get("decisions") or []

    lines = [
        "## Task",
        "",
        task["description"],
        "",
        "## Repository",
        "",
        task.get("repo", story_issue.get("repo", "")),
        "",
        "## Traceability",
        "",
        f"- **Story:** {story_id} (#{story_num})",
        f"- **Acceptance:** {task.get('acceptance', '')}",
    ]
    if duration:
        lines.append(f"- **Duration estimate:** {duration}")
    if branch:
        lines.extend(["", "## Development branch", "", f"`{branch}`"])
    if decisions:
        lines.extend(["", "## Decisions", ""])
        for decision in decisions:
            lines.append(f"- {decision}")
    lines.extend(["", "## Scope", "", *_format_scope_table(task), "", "## Tests", "", *_format_tests(task)])
    if patterns:
        lines.extend(["", "## Patterns", ""])
        for pattern in patterns:
            lines.append(f"- Mirror {pattern}")
    lines.extend(["", "## Dependencies", "", *_format_blockers(blocker_refs or [])])
    if spec_path:
        lines.extend(["", f"Spec file: `{spec_path}`"])
    return "\n".join(lines)


def resolve_blocking_ref(
    blocking: dict[str, Any],
    work_issues: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """Return (repo, number, manifest_entry) for a blocker."""
    kind = blocking.get("kind", "issue")
    if kind == "task":
        task_id = blocking["id"]
        entry = work_issues.get(task_id)
        if not entry or entry.get("number") is None:
            raise SystemExit(f"blocker task {task_id} not found in work_issues")
        return entry["repo"], str(entry["number"]), {
            "repo": entry["repo"],
            "number": int(entry["number"]),
            "kind": "task",
            "task_id": task_id,
            "reason": blocking.get("reason"),
        }
    repo = blocking["repo"]
    number = int(blocking["number"])
    return repo, str(number), {
        "repo": repo,
        "number": number,
        "kind": "issue",
        "reason": blocking.get("reason"),
    }


def apply_blockers(
    blockers: list[dict[str, Any]],
    work_issues: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Attach direct blockers; return blocked_task_id -> blocker refs for body render."""
    task_blockers: dict[str, list[dict[str, Any]]] = {tid: [] for tid in work_issues}
    seen_edges: set[tuple[str, str]] = set()

    for edge in blockers:
        blocked_id = edge["blocked_task_id"]
        blocked_entry = work_issues.get(blocked_id)
        if not blocked_entry or not blocked_entry.get("node_id"):
            raise SystemExit(f"blocked task {blocked_id} missing from work_issues")

        _repo, _num, ref = resolve_blocking_ref(edge["blocking"], work_issues)
        if edge["blocking"].get("kind") == "task":
            blocker_entry = work_issues[edge["blocking"]["id"]]
            blocking_node_id = blocker_entry["node_id"]
        else:
            blocking_node_id = issue_ref(
                edge["blocking"]["repo"], int(edge["blocking"]["number"])
            ).node_id

        edge_key = (blocked_entry["node_id"], blocking_node_id)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)

        if not dry_run and blocked_by_supported():
            try:
                add_blocked_by(blocked_entry["node_id"], blocking_node_id)
            except subprocess.CalledProcessError as exc:
                print(f"warn: addBlockedBy failed for {blocked_id}: {exc}", file=sys.stderr)

        task_blockers.setdefault(blocked_id, []).append(ref)

    return task_blockers


def ensure_project_item(manifest: dict[str, Any], issue_url: str, *, dry_run: bool) -> None:
    project = manifest.get("project") or {}
    owner = project.get("owner")
    number = project.get("number")
    if not owner or not number or dry_run:
        return
    try:
        project_item_add(owner, int(number), issue_url)
    except subprocess.CalledProcessError as exc:
        print(f"warn: project item-add failed: {exc}", file=sys.stderr)


def _resolve_story_issue(
    payload: dict[str, Any],
    manifest: dict[str, Any],
) -> tuple[IssueRef, dict[str, Any]]:
    story = payload.get("story_issue")
    if not story:
        raise SystemExit("payload missing story_issue")

    story_repo = story["repo"]
    story_number = int(story["number"])
    story_ref = issue_ref(story_repo, story_number)

    story_meta = {
        "repo": story_repo,
        "number": story_number,
        "id": story.get("id"),
    }
    if not story_meta["id"]:
        for sid, entry in manifest.get("stories", {}).items():
            if int(entry.get("number", 0)) == story_number:
                story_meta["id"] = sid
                break
    return story_ref, story_meta


def cmd_publish_plan(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    normalize_issue_hierarchy_payload(payload)
    manifest_path = Path(args.manifest_path) if args.manifest_path else None
    manifest = load_manifest(manifest_path) if manifest_path else {}

    auth_payload = manifest if manifest else payload
    if not args.dry_run:
        ensure_project_auth(auth_payload)

    story_ref, story_meta = _resolve_story_issue(payload, manifest)
    spec_path = manifest.get("spec_path") or payload.get("spec_path")
    hierarchy = manifest.get("hierarchy", "sub_issues")
    work_issues = dict(manifest.get("work_issues", {}))
    work_labels = labels_for_layer(payload, "work")
    work_issue_type = issue_type_for_layer(payload, "work")
    project_title = (manifest.get("project") or {}).get("title")
    project_cfg = resolve_project_config(
        manifest,
        payload,
        default_owner=parse_repo(story_meta["repo"])[0],
    )
    link_branches = linked_branches_supported()
    story_id = story_meta.get("id")

    # Pass 1: create or update task issues (no blocker section yet)
    for task in payload.get("tasks", []):
        task_id = task["id"]
        task_repo = task.get("repo") or story_meta["repo"]
        task_branch = task_branch_name(task_id, task["title"])
        branch_base = resolve_task_branch_base(task_repo, manifest, story_id)
        title = f"Task: {task['title']}"
        body = render_work_body_v2(
            task,
            story_meta,
            spec_path,
            blocker_refs=[],
            branch=task_branch,
        )

        existing = work_issues.get(task_id)
        if existing and existing.get("number"):
            ref = ensure_open_issue(task_repo, int(existing["number"]), task_id)
            if not args.dry_run:
                edit_issue(task_repo, ref.number, title, body)
                ensure_hierarchy_issue_classification(
                    task_repo, ref.number, work_issue_type
                )
        else:
            if args.dry_run:
                ref = IssueRef(number=0, node_id="DRY_RUN", url="")
            else:
                ref = create_issue_resilient(
                    task_repo,
                    title,
                    body,
                    work_labels,
                    project_title,
                    manifest,
                    issue_type=work_issue_type,
                )
                if hierarchy != "flat":
                    add_sub_issue(story_ref.node_id, ref.node_id)
                ensure_hierarchy_issue_classification(
                    task_repo, ref.number, work_issue_type
                )

        if not args.dry_run and ref.number:
            link_issue_branch(
                task_repo,
                ref.number,
                task_branch,
                branch_base,
                enabled=link_branches,
            )

        file_paths = task.get("files", [])
        if file_paths and isinstance(file_paths[0], dict):
            file_paths = [f["path"] for f in file_paths]

        work_issues[task_id] = {
            "number": ref.number,
            "node_id": ref.node_id,
            "url": ref.url,
            "repo": task_repo,
            "branch": task_branch,
            "story_id": story_meta.get("id"),
            "story_issue": {
                "repo": story_meta["repo"],
                "number": story_meta["number"],
            },
            "duration_estimate": task.get("duration_estimate"),
            "files": file_paths,
            "blockers": [],
            "published_at": utc_now_iso(),
        }

        if project_cfg and ref.url:
            ensure_project_estimate(
                project_cfg,
                ref.url,
                task.get("duration_estimate"),
                dry_run=args.dry_run,
            )

    # Pass 2: blockers (after all tasks exist)
    blockers = payload.get("blockers", [])
    task_blocker_refs = apply_blockers(blockers, work_issues, dry_run=args.dry_run)

    # Pass 3: refresh bodies with dependency section + persist blocker refs on manifest entries
    for task in payload.get("tasks", []):
        task_id = task["id"]
        entry = work_issues[task_id]
        task_repo = entry["repo"]
        refs = task_blocker_refs.get(task_id, [])
        entry["blockers"] = refs
        title = f"Task: {task['title']}"
        body = render_work_body_v2(
            task,
            story_meta,
            spec_path,
            blocker_refs=refs,
            branch=entry.get("branch"),
        )
        if not args.dry_run and entry.get("number"):
            edit_issue(task_repo, int(entry["number"]), title, body)

    # Story implementation notes
    story_notes = payload.get("story_notes", "")
    if story_notes and not args.dry_run:
        append_story_notes(story_meta["repo"], story_meta["number"], story_notes)

    if manifest_path and manifest:
        if project_cfg:
            manifest["project"] = {**manifest.get("project", {}), **project_cfg}
        manifest["work_issues"] = work_issues
        manifest["schema_version"] = "v1.1"
        manifest["status"] = "plan_published"
        if not args.dry_run:
            save_manifest(manifest_path, manifest)
            print(json.dumps(manifest, indent=2))
    elif not args.dry_run:
        print(json.dumps({"work_issues": work_issues}, indent=2))
    return 0


def cmd_verify_plan(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.manifest_path)) if args.manifest_path else {}
    story_repo = args.story_repo
    story_number = int(args.story_number)

    if not story_repo:
        story_issue = manifest.get("work_issues", {})
        if story_issue:
            sample = next(iter(story_issue.values()), {})
            si = sample.get("story_issue", {})
            story_repo = si.get("repo")
            story_number = int(si.get("number", 0))
    if not story_repo or not story_number:
        raise SystemExit("story-repo and story-number required (or infer from manifest)")

    hierarchy = manifest.get("hierarchy", "sub_issues")
    sub_numbers = (
        list_sub_issue_numbers(story_repo, story_number)
        if hierarchy != "flat"
        else set()
    )

    errors: list[str] = []
    for task_id, entry in manifest.get("work_issues", {}).items():
        number = entry.get("number")
        task_repo = entry.get("repo")
        if not number or not task_repo:
            errors.append(f"{task_id}: incomplete manifest entry")
            continue
        if not entry.get("branch"):
            errors.append(f"{task_id}: missing branch in manifest")
        ref = issue_ref(task_repo, int(number))
        if ref.state != "OPEN":
            errors.append(f"{task_id}: issue #{number} is {ref.state}")
        if hierarchy != "flat" and int(number) not in sub_numbers:
            errors.append(
                f"{task_id}: #{number} in {task_repo} is not a sub-issue of "
                f"{story_repo}#{story_number}"
            )

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1

    print("verify-plan: ok")
    return 0


def issue_url(repo: str, number: int) -> str:
    return f"https://github.com/{repo}/issues/{number}"


def validate_estimate_rollup(
    parent_hours: float | None,
    item_hours: list[float],
    *,
    allow_drift: bool,
) -> tuple[float, list[str]]:
    """Return (total, warnings). Raises ValueError when rollup invalid."""
    total = sum(item_hours)
    warnings: list[str] = []
    if parent_hours is None:
        return total, warnings
    if not item_hours:
        warnings.append("warn: parent.hours set but items is empty")
        return total, warnings
    delta = abs(parent_hours - total)
    if delta > 0.01:
        msg = (
            f"parent.hours ({parent_hours}) != sum(items.hours) ({total}); "
            f"delta={delta:.2f}"
        )
        if allow_drift:
            warnings.append(f"warn: {msg}")
        else:
            raise ValueError(msg)
    return total, warnings


def cmd_apply_estimates(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    manifest: dict[str, Any] = {}
    if args.manifest_path:
        manifest = json.loads(Path(args.manifest_path).read_text(encoding="utf-8"))

    items: list[dict[str, Any]] = list(payload.get("items") or [])
    if not items:
        print("error: payload.items is required and must be non-empty", file=sys.stderr)
        return 1

    parent = payload.get("parent") or {}
    parent_hours_raw = parent.get("hours")
    parent_hours: float | None = None
    if parent_hours_raw is not None:
        parent_hours = float(parent_hours_raw)

    item_hours: list[float] = []
    for row in items:
        hours = row.get("hours")
        if hours is None:
            print(
                f"error: items[{row.get('number')}] missing hours",
                file=sys.stderr,
            )
            return 1
        item_hours.append(float(hours))

    try:
        total, warnings = validate_estimate_rollup(
            parent_hours,
            item_hours,
            allow_drift=bool(args.allow_rollup_drift),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for warning in warnings:
        print(warning, file=sys.stderr)

    project = resolve_project_config(manifest, payload)
    if not project:
        print(
            "error: could not resolve GitHub project; set payload.project or "
            "manifest.project",
            file=sys.stderr,
        )
        return 1

    owner = project["owner"]
    number = int(project["number"])
    if not get_org_issue_estimate_field_id(owner):
        print(
            "warn: organization has no Estimate issue field; skipped apply-estimates",
            file=sys.stderr,
        )
        return 1

    applied: list[tuple[int, float]] = []
    for row in items:
        repo = row.get("repo")
        issue_number = row.get("number")
        hours = float(row["hours"])
        if not repo or issue_number is None:
            print(f"error: item missing repo or number: {row}", file=sys.stderr)
            return 1
        if args.dry_run:
            applied.append((int(issue_number), hours))
            continue
        try:
            set_issue_estimate_field(owner, str(repo), int(issue_number), hours)
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            print(
                f"error: Estimate field update failed for #{issue_number}: {exc}",
                file=sys.stderr,
            )
            return 1
        applied.append((int(issue_number), hours))

    parent_repo = parent.get("repo")
    parent_number = parent.get("number")
    if parent_repo and parent_number is not None:
        rollup_hours = parent_hours if parent_hours is not None else total
        if args.dry_run:
            applied.append((int(parent_number), rollup_hours))
        else:
            try:
                set_issue_estimate_field(
                    owner,
                    str(parent_repo),
                    int(parent_number),
                    rollup_hours,
                )
                applied.append((int(parent_number), rollup_hours))
            except (RuntimeError, subprocess.CalledProcessError) as exc:
                print(
                    f"error: parent Estimate field update failed: {exc}",
                    file=sys.stderr,
                )
                return 1

    mode = "dry-run" if args.dry_run else "applied"
    print(f"apply-estimates {mode}: project {owner}#{number}")
    for issue_number, hours in applied:
        print(f"  #{issue_number}: {hours:g}h")
    print(f"  children_total: {total:g}h")
    return 0


def cmd_finish_plan(args: argparse.Namespace) -> int:
    """Publish task issues then verify — single entry point for /gh-plan."""
    payload_path = Path(args.input)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    story = payload.get("story_issue")
    if not story:
        raise SystemExit("payload missing story_issue")

    publish_args = argparse.Namespace(
        repo=args.repo,
        manifest_path=args.manifest_path,
        input=args.input,
        dry_run=args.dry_run,
    )
    rc = cmd_publish_plan(publish_args)
    if rc != 0:
        return rc

    if args.dry_run:
        print("finish-plan: dry-run publish complete (verify skipped)")
        return 0

    verify_args = argparse.Namespace(
        manifest_path=args.manifest_path,
        story_repo=story["repo"],
        story_number=int(story["number"]),
    )
    return cmd_verify_plan(verify_args)


FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
STORY_INDEX_SECTION_RE = re.compile(
    r"^## User story index\b.*?(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)

SPEC_TEMPLATE_PATH = _COMMANDS_DIR.parent.parent / "docs" / "specs" / "SPEC.md.template"
USER_STORY_TEMPLATE_PATH = _COMMANDS_DIR.parent.parent / "docs" / "user-stories" / "user-story.md.template"

SPEC_REQUIRED_SECTIONS = (
    "Objective",
    "Tech Stack",
    "Commands",
    "Project Structure",
    "Code Style",
    "Testing Strategy",
    "Boundaries",
    "Success Criteria",
    "Open Questions",
    "User story index",
)

AC_SCENARIO_LINE_RE = re.compile(
    r"^\s*[-*]\s*\*\*(Given|When|Then)\*\*",
    re.MULTILINE | re.IGNORECASE,
)

STORY_INDEX_ROW_RE = re.compile(r"^\|\s*(US-\d+)\s*\|", re.MULTILINE)


def spec_docs_path(slug: str) -> str:
    return f"docs/specs/{slug}/SPEC.md"


def spec_template_text() -> str:
    if not SPEC_TEMPLATE_PATH.is_file():
        raise SystemExit(f"spec template not found: {SPEC_TEMPLATE_PATH}")
    return SPEC_TEMPLATE_PATH.read_text(encoding="utf-8")


def render_spec_template(feature_title: str) -> str:
    return spec_template_text().replace("{{FEATURE_TITLE}}", feature_title)


def user_story_template_text() -> str:
    if not USER_STORY_TEMPLATE_PATH.is_file():
        raise SystemExit(f"user-story template not found: {USER_STORY_TEMPLATE_PATH}")
    return USER_STORY_TEMPLATE_PATH.read_text(encoding="utf-8")


def render_user_story_doc(
    story_id: str,
    story_title: str,
    story_line: str,
    acceptance_scenarios: list[dict[str, Any]],
    feature_title: str,
    spec_slug: str,
    story_issue_url: str,
    story_branch: str,
) -> str:
    ac_lines: list[str] = []
    for scenario in acceptance_scenarios:
        ac_lines.append(f"### {scenario['id']} — {scenario.get('name', '')}")
        for step in scenario.get("steps", []):
            ac_lines.append(f"- **{step['keyword']}** {step['text']}")
        ac_lines.append("")
    ac_section = "\n".join(ac_lines).rstrip() or "<!-- No acceptance criteria defined -->"
    return (
        user_story_template_text()
        .replace("{{STORY_ID}}", story_id)
        .replace("{{STORY_TITLE}}", story_title)
        .replace("{{STORY_LINE}}", story_line)
        .replace("{{AC_SECTION}}", ac_section)
        .replace("{{FEATURE_TITLE}}", feature_title)
        .replace("{{SPEC_SLUG}}", spec_slug)
        .replace("{{STORY_ISSUE_URL}}", story_issue_url)
        .replace("{{STORY_BRANCH}}", story_branch)
    )


def write_user_story_docs(
    payload: dict[str, Any],
    manifest: dict[str, Any],
    repo_path: str,
    *,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    feature_title = payload.get("title", payload.get("feature_slug", ""))
    spec_slug = payload.get("feature_slug", "")
    user_stories_dir = Path(repo_path) / "docs" / "user-stories"
    results: list[dict[str, Any]] = []
    for story in payload.get("stories", []):
        story_id = story["id"]
        story_title = story.get("title", "")
        story_branch = story_branch_name(story_id, story_title)
        branch_slug = story_branch.replace("user-story/", "")
        doc_path = user_stories_dir / f"{branch_slug}.md"
        manifest_entry = manifest.get("stories", {}).get(story_id, {})
        story_issue_url = manifest_entry.get("url", "TBD")
        content = render_user_story_doc(
            story_id=story_id,
            story_title=story_title,
            story_line=story.get("story_line", ""),
            acceptance_scenarios=story.get("acceptance_scenarios", []),
            feature_title=feature_title,
            spec_slug=spec_slug,
            story_issue_url=story_issue_url,
            story_branch=story_branch,
        )
        result: dict[str, Any] = {
            "story_id": story_id,
            "doc_path": str(doc_path.relative_to(repo_path)),
            "skipped": False,
            "dry_run": dry_run,
        }
        if doc_path.exists():
            result["skipped"] = True
            result["reason"] = "file already exists (use --force to overwrite)"
            results.append(result)
            print(
                f"write_user_story_docs: skipping {doc_path} (already exists)",
                file=sys.stderr,
            )
            continue
        if not dry_run:
            user_stories_dir.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(content, encoding="utf-8")
            result["written"] = True
        results.append(result)
    return results


def cmd_render_user_story_docs(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    manifest = load_manifest(Path(args.manifest_path))
    repo_path = str(Path(args.repo_path).resolve())
    force = getattr(args, "force", False)
    if force:
        for story in payload.get("stories", []):
            story_id = story["id"]
            story_branch = story_branch_name(story_id, story.get("title", ""))
            branch_slug = story_branch.replace("user-story/", "")
            doc_path = Path(repo_path) / "docs" / "user-stories" / f"{branch_slug}.md"
            if doc_path.exists():
                doc_path.unlink()
    results = write_user_story_docs(
        payload, manifest, repo_path, dry_run=bool(args.dry_run)
    )
    print(json.dumps({"user_story_docs": results}, indent=2))
    return 0


def body_without_story_index(body: str) -> str:
    return STORY_INDEX_SECTION_RE.sub("", body)


def has_section(body: str, title: str) -> bool:
    return re.search(rf"^## {re.escape(title)}\b", body, re.MULTILINE) is not None


def parse_story_index_rows(body: str) -> dict[str, dict[str, str]]:
    match = STORY_INDEX_SECTION_RE.search(body)
    if not match:
        return {}
    rows: dict[str, dict[str, str]] = {}
    for line in match.group(0).splitlines():
        row_match = STORY_INDEX_ROW_RE.match(line)
        if not row_match:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        rows[row_match.group(1)] = {
            "issue": cells[1],
            "repos": cells[2],
            "ac_ids": cells[3],
        }
    return rows


def verify_spec_core(
    body: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    for section in SPEC_REQUIRED_SECTIONS:
        if not has_section(body, section):
            errors.append(f"missing required section: ## {section}")

    if AC_SCENARIO_LINE_RE.search(body_without_story_index(body)):
        errors.append(
            "SPEC.md contains Given/When/Then AC text outside the story index; "
            "canonical AC belongs in publish payload / GitHub story issues only"
        )

    index_rows = parse_story_index_rows(body)
    if has_section(body, "User story index") and not index_rows:
        errors.append("story index table has no US-* rows")

    if payload:
        payload_stories = payload.get("stories") or []
        payload_ids = [story["id"] for story in payload_stories if story.get("id")]
        index_ids = set(index_rows)
        payload_id_set = set(payload_ids)

        for story_id in payload_ids:
            if story_id not in index_rows:
                errors.append(f"story index missing row for {story_id} from publish payload")
                continue
            row = index_rows[story_id]
            if not row["repos"]:
                errors.append(f"story index Repositories empty for {story_id}")
            if not row["ac_ids"]:
                errors.append(f"story index AC IDs empty for {story_id}")

        extra = sorted(index_ids - payload_id_set)
        if extra:
            errors.append(
                f"story index lists stories not in publish payload: {', '.join(extra)}"
            )

        for story in payload_stories:
            story_id = story.get("id")
            if not story_id or story_id not in index_rows:
                continue
            expected_ac = ", ".join(
                scenario["id"]
                for scenario in story.get("acceptance_scenarios") or []
                if scenario.get("id")
            )
            if expected_ac and index_rows[story_id]["ac_ids"] != expected_ac:
                warnings.append(
                    f"{story_id}: story index AC IDs ({index_rows[story_id]['ac_ids']!r}) "
                    f"differ from payload ({expected_ac!r})"
                )

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def cmd_init_spec_artifacts(args: argparse.Namespace) -> int:
    slug = args.slug.strip()
    title = args.title.strip()
    if not slug or not title:
        raise SystemExit("--slug and --title are required")
    repo_path = str(Path(args.repo_path).resolve())
    spec_rel = spec_docs_path(slug)
    spec_path = Path(repo_path) / spec_rel

    if spec_path.exists() and not args.force:
        raise SystemExit(
            f"SPEC.md already exists: {spec_path} (use --force to overwrite template only)"
        )

    template = render_spec_template(title)
    result: dict[str, Any] = {
        "slug": slug,
        "title": title,
        "spec_path": spec_rel,
        "repo_path": repo_path,
        "created": False,
    }

    if not args.dry_run:
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(template, encoding="utf-8")
        result["created"] = True
    else:
        result["action"] = "dry-run"

    if args.bootstrap:
        if not args.repo:
            raise SystemExit("--repo is required with --bootstrap")
        branch_result = bootstrap_spec_branch_core(
            args.repo,
            repo_path,
            slug,
            push=bool(args.push),
            dry_run=bool(args.dry_run),
        )
        result["branch"] = branch_result

    print(json.dumps(result, indent=2))
    return 0


def cmd_verify_spec(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec_path)
    if not spec_path.is_file():
        raise SystemExit(f"spec file not found: {spec_path}")
    body = spec_path.read_text(encoding="utf-8")
    payload: dict[str, Any] | None = None
    if args.input:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = verify_spec_core(body, payload)
    result["spec_path"] = str(spec_path)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


def bootstrap_spec_branch_core(
    github_repo: str,
    repo_path: str,
    slug: str,
    *,
    push: bool,
    dry_run: bool,
) -> dict[str, Any]:
    branch = spec_branch_name(slug)
    result: dict[str, Any] = {
        "repo": github_repo,
        "path": repo_path,
        "branch": branch,
        "pushed": False,
    }
    if dry_run:
        result["action"] = "dry-run"
        return result
    default = default_branch(github_repo)
    result["default_branch"] = default
    git_run(["fetch", "origin", default], repo_path)
    created = git_run(
        ["checkout", "-B", branch, f"origin/{default}"],
        repo_path,
        check=False,
    )
    result["action"] = (
        "created_from_default" if created.returncode == 0 else "checkout_existing"
    )
    if created.returncode != 0:
        git_run(["checkout", branch], repo_path)
    if push:
        git_run(["push", "-u", "origin", branch], repo_path)
        result["pushed"] = True
    return result


def bootstrap_story_branch_core(
    github_repo: str,
    repo_path: str,
    story_branch: str,
    spec_branch: str,
    *,
    push: bool,
    dry_run: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "repo": github_repo,
        "path": repo_path,
        "branch": story_branch,
        "base": spec_branch,
        "pushed": False,
    }
    if dry_run:
        result["action"] = "dry-run"
        return result
    git_run(["fetch", "origin", spec_branch], repo_path, check=False)
    created = git_run(
        ["checkout", "-B", story_branch, f"origin/{spec_branch}"],
        repo_path,
        check=False,
    )
    result["action"] = (
        "created_from_spec" if created.returncode == 0 else "checkout_existing"
    )
    if created.returncode != 0:
        git_run(["checkout", story_branch], repo_path, check=False)
    if push:
        git_run(["push", "-u", "origin", story_branch], repo_path)
        result["pushed"] = True
    return result


def format_project_ref(project: dict[str, Any] | None) -> str | None:
    if not project:
        return None
    owner = project.get("owner")
    number = project.get("number")
    if owner and number is not None:
        return f"{owner}/projects/{number}"
    return None


def gh_spec_frontmatter(manifest: dict[str, Any]) -> dict[str, str]:
    repo = manifest["repo"]
    parent_num = manifest.get("parent_issue", {}).get("number")
    if not parent_num:
        raise SystemExit("manifest missing parent_issue.number (publish first)")
    spec_path = manifest.get("spec_path", "")
    manifest_path = spec_path.replace("SPEC.md", "gh-spec.manifest.json")
    out: dict[str, str] = {
        "parent_issue": f"{repo}#{parent_num}",
        "manifest": manifest_path,
    }
    project_ref = format_project_ref(manifest.get("project"))
    if project_ref:
        out["project"] = project_ref
    return out


def merge_gh_spec_frontmatter(body: str, gh_spec: dict[str, str]) -> str:
    lines = ["---", "gh_spec:"]
    for key, value in gh_spec.items():
        lines.append(f"  {key}: {value}")
    lines.append("---")
    block = "\n".join(lines) + "\n"
    if FRONTMATTER_RE.match(body):
        return FRONTMATTER_RE.sub(block, body, count=1)
    return block + "\n" + body.lstrip("\n")


def render_story_index_section(manifest: dict[str, Any]) -> str:
    home = manifest["repo"]
    rows = [
        "## User story index",
        "",
        "Canonical AC text is in GitHub sub-issues.",
        "",
        "| Story | Issue | Repositories | AC IDs |",
        "|-------|-------|--------------|--------|",
    ]
    for story_id in sorted(manifest.get("stories", {}).keys()):
        entry = manifest["stories"][story_id]
        number = entry.get("number", "TBD")
        url = entry.get("url") or ""
        issue_cell = f"[#{number}]({url})" if url else f"#{number}"
        repos_label = format_repos_index(story_repos_from_manifest(entry, home))
        ac_ids = ", ".join(entry.get("ac_ids") or [])
        rows.append(f"| {story_id} | {issue_cell} | {repos_label} | {ac_ids} |")
    return "\n".join(rows)


def upsert_story_index(body: str, section: str) -> str:
    if STORY_INDEX_SECTION_RE.search(body):
        return STORY_INDEX_SECTION_RE.sub(section.rstrip() + "\n", body)
    return body.rstrip() + "\n\n" + section + "\n"


def affected_github_repos(
    payload: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
) -> list[str]:
    if manifest and manifest.get("repos"):
        return [entry["repo"] for entry in manifest["repos"]]
    if payload and payload.get("repo"):
        home = payload["repo"]
        return [repo.name for repo in union_affected_repos(payload, home)]
    raise SystemExit("provide --manifest-path or --input payload with repo and stories/repos")


def cmd_bootstrap_spec_branch(args: argparse.Namespace) -> int:
    result = bootstrap_spec_branch_core(
        args.repo,
        args.repo_path,
        args.slug,
        push=bool(args.push),
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(result, indent=2))
    return 0


def cmd_bootstrap_spec_branches(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    slug = payload["feature_slug"]
    home = payload["repo"]
    roots = workspace_roots_from_args(args)
    repos = union_affected_repos(payload, home)
    results: list[dict[str, Any]] = []
    for story_repo in repos:
        path = (
            "(dry-run)"
            if args.dry_run
            else resolve_repo_checkout(story_repo.name, roots)
        )
        results.append(
            bootstrap_spec_branch_core(
                story_repo.name,
                path,
                slug,
                push=bool(args.push),
                dry_run=bool(args.dry_run),
            )
        )
    print(json.dumps({"feature_slug": slug, "branches": results}, indent=2))
    return 0


def cmd_bootstrap_story_branches(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.manifest_path))
    spec_branch = manifest.get("spec_branch")
    if not spec_branch:
        raise SystemExit("manifest missing spec_branch")
    slug = manifest.get("feature_slug", "")
    roots = workspace_roots_from_args(args)
    home = manifest["repo"]
    story_filter = args.story
    results: list[dict[str, Any]] = []
    for story_id, entry in sorted(manifest.get("stories", {}).items()):
        if story_filter and story_id != story_filter:
            continue
        story_branch = entry.get("branch")
        if not story_branch:
            raise SystemExit(f"manifest story {story_id} missing branch")
        for repo in story_repos_from_manifest(entry, home):
            path = (
                "(dry-run)"
                if args.dry_run
                else resolve_repo_checkout(repo.name, roots)
            )
            results.append(
                bootstrap_story_branch_core(
                    repo.name,
                    path,
                    story_branch,
                    spec_branch,
                    push=bool(args.push),
                    dry_run=bool(args.dry_run),
                )
            )
    print(
        json.dumps(
            {"feature_slug": slug, "spec_branch": spec_branch, "branches": results},
            indent=2,
        )
    )
    return 0


def cmd_verify_branches(args: argparse.Namespace) -> int:
    payload: dict[str, Any] | None = None
    manifest: dict[str, Any] | None = None
    if args.input:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if args.manifest_path:
        manifest = load_manifest(Path(args.manifest_path))
    if payload and not manifest:
        slug = payload["feature_slug"]
        spec_branch = spec_branch_name(slug)
    else:
        if not manifest:
            raise SystemExit("provide --manifest-path or --input")
        spec_branch = manifest.get("spec_branch")
        if not spec_branch:
            raise SystemExit("manifest missing spec_branch")
        payload = payload or {}

    github_repos = affected_github_repos(payload or None, manifest)
    errors: list[str] = []
    for github_repo in github_repos:
        if not remote_branch_exists(github_repo, spec_branch):
            errors.append(f"{github_repo}: missing remote branch {spec_branch!r}")

    if args.require_story_branches:
        if not manifest:
            raise SystemExit("--require-story-branches needs --manifest-path")
        home = manifest["repo"]
        for story_id, entry in manifest.get("stories", {}).items():
            story_branch = entry.get("branch")
            if not story_branch:
                errors.append(f"{story_id}: missing branch in manifest")
                continue
            for repo in story_repos_from_manifest(entry, home):
                if not remote_branch_exists(repo.name, story_branch):
                    errors.append(
                        f"{story_id} {repo.name}: missing remote branch {story_branch!r}"
                    )

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    print("verify-branches: ok")
    return 0


def cmd_link_branches(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.manifest_path))
    repo = args.repo or manifest.get("repo")
    if not repo:
        raise SystemExit("repo required")
    spec_branch = manifest.get("spec_branch")
    if not spec_branch:
        raise SystemExit("manifest missing spec_branch")
    if not linked_branches_supported():
        print("link-branches: linked_branches unavailable; skipped", file=sys.stderr)
        return 0

    parent_number = manifest.get("parent_issue", {}).get("number")
    if not parent_number:
        raise SystemExit("manifest missing parent_issue.number")

    base = default_branch(repo)
    link_issue_branch(repo, int(parent_number), spec_branch, base, enabled=True)

    linked: list[dict[str, Any]] = [
        {"issue": int(parent_number), "branch": spec_branch, "repo": repo}
    ]
    for story_id, entry in manifest.get("stories", {}).items():
        number = entry.get("number")
        story_branch = entry.get("branch")
        if not number or not story_branch:
            raise SystemExit(f"manifest story {story_id} missing number or branch")
        link_issue_branch(repo, int(number), story_branch, spec_branch, enabled=True)
        linked.append(
            {"story": story_id, "issue": int(number), "branch": story_branch, "repo": repo}
        )

    print(json.dumps({"linked": linked}, indent=2))
    return 0


def cmd_update_spec(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest_path)
    spec_path = Path(args.spec_path)
    manifest = load_manifest(manifest_path)
    if not spec_path.is_file():
        raise SystemExit(f"spec file not found: {spec_path}")

    body = spec_path.read_text(encoding="utf-8")
    gh_spec = gh_spec_frontmatter(manifest)
    body = merge_gh_spec_frontmatter(body, gh_spec)
    body = upsert_story_index(body, render_story_index_section(manifest))

    if args.dry_run:
        print(body)
        return 0

    spec_path.write_text(body, encoding="utf-8")
    print(json.dumps({"spec_path": str(spec_path), "updated": True}, indent=2))
    return 0


def post_publish_comment(
    manifest: dict[str, Any],
    spec_path: str,
    repo_path: str | None,
) -> None:
    parent_number = manifest.get("parent_issue", {}).get("number")
    repo = manifest.get("repo")
    if not parent_number or not repo:
        return
    sha = "unknown"
    if repo_path:
        try:
            sha = git_run(["rev-parse", "--short", "HEAD"], repo_path).stdout.strip()
        except subprocess.CalledProcessError:
            pass
    gh_run(
        [
            "issue",
            "comment",
            str(parent_number),
            "--repo",
            repo,
            "--body",
            f"Spec published. File: `{spec_path}` @ `{sha}`",
        ]
    )


def cmd_finish_spec(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    normalize_issue_hierarchy_payload(payload)
    manifest_path = Path(args.manifest_path)
    spec_path = Path(args.spec_path)
    repo = args.repo or payload["repo"]
    roots = workspace_roots_from_args(args)
    dry_run = bool(args.dry_run)

    if not spec_path.is_file():
        raise SystemExit(f"spec file not found: {spec_path}")
    spec_check = verify_spec_core(spec_path.read_text(encoding="utf-8"), payload)
    if not spec_check["ok"]:
        print(json.dumps(spec_check, indent=2), file=sys.stderr)
        raise SystemExit("verify-spec failed; fix SPEC.md before finish-spec")

    preflight_args = argparse.Namespace()
    preflight_rc = cmd_preflight(preflight_args)
    if preflight_rc != 0 and not dry_run:
        print("finish-spec: preflight reported sub_issues unavailable (flat fallback)", file=sys.stderr)

    verify_args = argparse.Namespace(
        input=args.input,
        manifest_path=None,
        require_story_branches=False,
    )
    if cmd_verify_branches(verify_args) != 0 and not dry_run:
        raise SystemExit(
            "spec branches not on remote in all affected repos; "
            "commit, push, or run bootstrap-spec-branches --push"
        )

    publish_args = argparse.Namespace(
        repo=repo,
        manifest_path=str(manifest_path),
        input=args.input,
        dry_run=dry_run,
    )
    if cmd_publish(publish_args) != 0:
        return 1

    manifest = load_manifest(manifest_path)
    verify_issue_args = argparse.Namespace(repo=repo, manifest_path=str(manifest_path))
    if not dry_run and cmd_verify(verify_issue_args) != 0:
        return 1

    if not args.skip_story_branches:
        bootstrap_args = argparse.Namespace(
            manifest_path=str(manifest_path),
            story=None,
            workspace_root=getattr(args, "workspace_root", None),
            repo_path=getattr(args, "repo_path", None),
            push=not dry_run,
            dry_run=dry_run,
        )
        cmd_bootstrap_story_branches(bootstrap_args)

    if not dry_run:
        link_args = argparse.Namespace(manifest_path=str(manifest_path), repo=repo)
        cmd_link_branches(link_args)

        update_args = argparse.Namespace(
            manifest_path=str(manifest_path),
            spec_path=str(spec_path),
            repo_path=args.repo_path,
            dry_run=False,
        )
        cmd_update_spec(update_args)

        home_path = args.repo_path or find_local_repo_path(repo, roots)

        manifest = load_manifest(manifest_path)
        write_user_story_docs(payload, manifest, home_path, dry_run=False)

        post_publish_comment(manifest, str(spec_path), home_path)

    print("finish-spec: ok")
    return 0


def cmd_sync_plan_branches(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.manifest_path))
    home_repo = manifest.get("repo")
    if not home_repo:
        raise SystemExit("manifest missing repo")
    spec_branch = manifest.get("spec_branch")
    feature_slug = manifest.get("feature_slug")
    if not spec_branch or not feature_slug:
        raise SystemExit("manifest missing spec_branch or feature_slug")

    story_id = args.story_id
    story_entry = (manifest.get("stories") or {}).get(story_id)
    if not story_entry:
        raise SystemExit(f"manifest missing stories.{story_id}")
    story_branch = story_entry.get("branch")
    if not story_branch:
        raise SystemExit(f"manifest story {story_id} missing branch")

    roots = workspace_roots_from_args(args)
    repo_path = args.repo_path or resolve_repo_checkout(home_repo, roots)
    default = default_branch(home_repo)
    dry_run = bool(args.dry_run)
    mode = args.mode or "plan"

    work_issues = manifest.get("work_issues") or {}
    enriched_work: dict[str, Any] = {}
    if mode == "update-plan" and work_issues:
        for task_id, entry in work_issues.items():
            if entry.get("story_id") != story_id:
                continue
            task_repo = entry.get("repo")
            if not task_repo:
                continue
            copy = dict(entry)
            try:
                copy["_repo_path"] = resolve_repo_checkout(task_repo, roots)
            except SystemExit:
                copy["_repo_path"] = None
            enriched_work[task_id] = copy
        work_issues = enriched_work

    other_repos: list[dict[str, str]] = []
    if args.other_repo:
        for spec in args.other_repo:
            if ":" not in spec:
                raise SystemExit(f"--other-repo must be owner/name:path, got {spec!r}")
            gh_repo, path = spec.split(":", 1)
            other_repos.append({"repo": gh_repo.strip(), "path": path.strip()})

    result = sync_plan_branches_core(
        home_repo=home_repo,
        repo_path=repo_path,
        default=default,
        spec_branch=spec_branch,
        story_branch=story_branch,
        feature_slug=feature_slug,
        mode=mode,
        work_issues=work_issues if mode == "update-plan" else None,
        story_id=story_id if mode == "update-plan" else None,
        other_repos=other_repos or None,
        dry_run=dry_run,
    )
    attach_sync_user_message(result)
    print(json.dumps(result, indent=2))
    if result.get("blocked_reason"):
        return 2
    return 0


def cmd_check_scope_drift(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.manifest_path))
    home_repo = manifest.get("repo")
    if not home_repo:
        raise SystemExit("manifest missing repo")
    spec_branch = manifest.get("spec_branch")
    if not spec_branch:
        raise SystemExit("manifest missing spec_branch")

    story_id = args.story_id
    story_entry = (manifest.get("stories") or {}).get(story_id)
    if not story_entry:
        raise SystemExit(f"manifest missing stories.{story_id}")
    story_branch = story_entry.get("branch")
    if not story_branch:
        raise SystemExit(f"manifest story {story_id} missing branch")

    roots = workspace_roots_from_args(args)
    repo_path = args.repo_path or resolve_repo_checkout(home_repo, roots)

    other_repos: list[dict[str, str]] = []
    if args.other_repo:
        for spec in args.other_repo:
            if ":" not in spec:
                raise SystemExit(f"--other-repo must be owner/name:path, got {spec!r}")
            gh_repo, path = spec.split(":", 1)
            other_repos.append({"repo": gh_repo.strip(), "path": path.strip()})

    fetch_issue_body = None if args.no_fetch_issues else issue_body

    result = check_scope_drift_core(
        manifest=manifest,
        story_id=story_id,
        home_repo=home_repo,
        repo_path=repo_path,
        pre_story_sha=args.pre_story_sha,
        post_story_sha=args.post_story_sha,
        spec_branch=spec_branch,
        story_branch=story_branch,
        other_repos=other_repos or None,
        fetch_issue_body=fetch_issue_body,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("outcome") != "drift" else 2


def cmd_render_message(args: argparse.Namespace) -> int:
    payload_path = Path(args.input)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    print(render_message(args.template, payload))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("preflight", help="Check sub-issue GraphQL support")

    init_spec = sub.add_parser(
        "init-spec-artifacts",
        help="Create docs/specs/<slug>/SPEC.md from template; optional spec branch bootstrap",
    )
    init_spec.add_argument("--slug", required=True)
    init_spec.add_argument("--title", required=True, help="Feature title for SPEC.md heading")
    init_spec.add_argument("--repo-path", required=True, help="Local git checkout (home repo)")
    init_spec.add_argument("--repo", help="owner/repo — required with --bootstrap")
    init_spec.add_argument(
        "--bootstrap",
        action="store_true",
        help="Also create/checkout spec/<slug> via bootstrap-spec-branch",
    )
    init_spec.add_argument("--push", action="store_true", help="Push spec branch when bootstrapping")
    init_spec.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing SPEC.md with template",
    )
    init_spec.add_argument("--dry-run", action="store_true")

    verify_spec = sub.add_parser(
        "verify-spec",
        help="Pre-publish SPEC.md checks (sections, story index, no duplicated AC text)",
    )
    verify_spec.add_argument("--spec-path", required=True)
    verify_spec.add_argument(
        "--input",
        help="Publish payload JSON — validates story index rows match payload stories",
    )

    publish = sub.add_parser("publish", help="Create/update spec parent + story issues")
    publish.add_argument("--repo", required=True)
    publish.add_argument("--manifest-path", required=True)
    publish.add_argument("--input", required=True, help="JSON publish payload path")
    publish.add_argument("--dry-run", action="store_true")

    verify = sub.add_parser("verify", help="Verify manifest against live issues")
    verify.add_argument("--repo")
    verify.add_argument("--manifest-path", required=True)

    fix_types = sub.add_parser(
        "fix-hierarchy-types",
        help="Apply issue types from manifest; strip legacy spec/user-story/task labels",
    )
    fix_types.add_argument("--repo")
    fix_types.add_argument("--manifest-path", required=True)

    plan = sub.add_parser("publish-plan", help="Create work-unit sub-issues under stories")
    plan.add_argument("--repo")
    plan.add_argument("--manifest-path", help="Optional manifest for idempotency")
    plan.add_argument("--input", required=True, help="JSON plan publish payload path")
    plan.add_argument("--dry-run", action="store_true")

    verify_plan = sub.add_parser("verify-plan", help="Verify work issues under a story")
    verify_plan.add_argument("--manifest-path")
    verify_plan.add_argument("--story-repo")
    verify_plan.add_argument("--story-number", type=int)

    finish = sub.add_parser(
        "finish-plan",
        help="publish-plan then verify-plan (required end of /gh-plan)",
    )
    finish.add_argument("--repo")
    finish.add_argument("--manifest-path", help="Optional manifest for idempotency")
    finish.add_argument("--input", required=True, help="JSON plan publish payload path")
    finish.add_argument("--dry-run", action="store_true")

    estimates = sub.add_parser(
        "apply-estimates",
        help="Set GitHub Project Estimate fields from gh-estimate-work payload",
    )
    estimates.add_argument("--input", required=True, help="JSON estimate payload path")
    estimates.add_argument(
        "--manifest-path",
        help="Optional manifest for project resolution",
    )
    estimates.add_argument("--dry-run", action="store_true")
    estimates.add_argument(
        "--allow-rollup-drift",
        action="store_true",
        help="Warn instead of failing when parent.hours != sum(items.hours)",
    )

    def add_workspace_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--workspace-root",
            action="append",
            help="Directory to scan for local repo checkouts (repeatable)",
        )
        p.add_argument("--repo-path", help="Explicit git checkout path (home repo)")

    bootstrap_one = sub.add_parser(
        "bootstrap-spec-branch",
        help="Create/checkout spec/<slug> in one local repo",
    )
    bootstrap_one.add_argument("--repo", required=True)
    bootstrap_one.add_argument("--slug", required=True)
    bootstrap_one.add_argument("--repo-path", required=True)
    bootstrap_one.add_argument("--push", action="store_true")
    bootstrap_one.add_argument("--dry-run", action="store_true")

    bootstrap_all = sub.add_parser(
        "bootstrap-spec-branches",
        help="Create/checkout spec/<slug> in every repo from publish payload",
    )
    bootstrap_all.add_argument("--input", required=True, help="Publish payload JSON path")
    bootstrap_all.add_argument("--push", action="store_true")
    bootstrap_all.add_argument("--dry-run", action="store_true")
    add_workspace_args(bootstrap_all)

    bootstrap_stories = sub.add_parser(
        "bootstrap-story-branches",
        help="Create/push user-story branches from manifest (per story × repo)",
    )
    bootstrap_stories.add_argument("--manifest-path", required=True)
    bootstrap_stories.add_argument("--story", help="Limit to one US-* id")
    bootstrap_stories.add_argument("--push", action="store_true")
    bootstrap_stories.add_argument("--dry-run", action="store_true")
    add_workspace_args(bootstrap_stories)

    verify_br = sub.add_parser(
        "verify-branches",
        help="Verify spec (and optionally story) branches exist on remotes",
    )
    verify_br.add_argument("--manifest-path")
    verify_br.add_argument("--input", help="Publish payload JSON (pre-publish)")
    verify_br.add_argument(
        "--require-story-branches",
        action="store_true",
        help="Also require story branches on remotes (post-publish)",
    )

    link_br = sub.add_parser(
        "link-branches",
        help="Link parent/story issues to development branches (home repo)",
    )
    link_br.add_argument("--manifest-path", required=True)
    link_br.add_argument("--repo", help="Home repo (default: manifest.repo)")

    update_spec = sub.add_parser(
        "update-spec",
        help="Write gh_spec frontmatter and story index into SPEC.md",
    )
    update_spec.add_argument("--manifest-path", required=True)
    update_spec.add_argument("--spec-path", required=True)
    update_spec.add_argument("--repo-path", help="Unused; reserved for future validation")
    update_spec.add_argument("--dry-run", action="store_true")

    finish_spec = sub.add_parser(
        "finish-spec",
        help="verify-branches → publish → verify → story branches → link → update-spec → comment",
    )
    finish_spec.add_argument("--repo", required=True)
    finish_spec.add_argument("--input", required=True, help="Publish payload JSON path")
    finish_spec.add_argument("--manifest-path", required=True)
    finish_spec.add_argument("--spec-path", required=True)
    finish_spec.add_argument(
        "--skip-story-branches",
        action="store_true",
        help="Skip bootstrap-story-branches (e.g. defer until later)",
    )
    finish_spec.add_argument("--dry-run", action="store_true")
    add_workspace_args(finish_spec)

    render_story_docs = sub.add_parser(
        "render-user-story-docs",
        help="Write docs/user-stories/<branch-slug>.md from template for each story in payload",
    )
    render_story_docs.add_argument("--input", required=True, help="Publish payload JSON path")
    render_story_docs.add_argument("--manifest-path", required=True)
    render_story_docs.add_argument("--repo-path", required=True)
    render_story_docs.add_argument("--force", action="store_true", help="Overwrite existing docs")
    render_story_docs.add_argument("--dry-run", action="store_true")

    sync_br = sub.add_parser(
        "sync-plan-branches",
        help="Fetch, started-gate, and rebase spec/story branches on home repo",
    )
    sync_br.add_argument("--manifest-path", required=True)
    sync_br.add_argument("--story-id", required=True, help="US-* id from manifest.stories")
    sync_br.add_argument(
        "--mode",
        choices=("plan", "update-plan"),
        default="plan",
        help="plan: may require user confirm when started; update-plan: hard stop",
    )
    sync_br.add_argument(
        "--other-repo",
        action="append",
        help="Listed repo checkout owner/name:/path (repeatable)",
    )
    sync_br.add_argument("--dry-run", action="store_true")
    add_workspace_args(sync_br)

    drift = sub.add_parser(
        "check-scope-drift",
        help="Compare task scope paths across pre/post story SHAs for /gh-update-plan",
    )
    drift.add_argument("--manifest-path", required=True)
    drift.add_argument("--story-id", required=True, help="US-* id from manifest.stories")
    drift.add_argument("--pre-story-sha", required=True)
    drift.add_argument("--post-story-sha", required=True)
    drift.add_argument(
        "--other-repo",
        action="append",
        help="Listed repo checkout owner/name:/path (repeatable)",
    )
    drift.add_argument(
        "--no-fetch-issues",
        action="store_true",
        help="Use manifest work_issues.files[] only; do not fetch task issue bodies",
    )
    add_workspace_args(drift)

    render_msg = sub.add_parser(
        "render-message",
        help="Render a planning user message template from JSON payload",
    )
    render_msg.add_argument(
        "--template",
        required=True,
        help="Template name (e.g. started-gate-stop, branch-started-confirm, update-plan-drift)",
    )
    render_msg.add_argument("--input", required=True, help="JSON payload path")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "preflight":
        return cmd_preflight(args)
    if args.command == "init-spec-artifacts":
        return cmd_init_spec_artifacts(args)
    if args.command == "verify-spec":
        return cmd_verify_spec(args)
    if args.command == "publish":
        return cmd_publish(args)
    if args.command == "verify":
        return cmd_verify(args)
    if args.command == "fix-hierarchy-types":
        return cmd_fix_hierarchy_types(args)
    if args.command == "publish-plan":
        return cmd_publish_plan(args)
    if args.command == "verify-plan":
        return cmd_verify_plan(args)
    if args.command == "finish-plan":
        return cmd_finish_plan(args)
    if args.command == "apply-estimates":
        return cmd_apply_estimates(args)
    if args.command == "bootstrap-spec-branch":
        return cmd_bootstrap_spec_branch(args)
    if args.command == "bootstrap-spec-branches":
        return cmd_bootstrap_spec_branches(args)
    if args.command == "bootstrap-story-branches":
        return cmd_bootstrap_story_branches(args)
    if args.command == "verify-branches":
        return cmd_verify_branches(args)
    if args.command == "link-branches":
        return cmd_link_branches(args)
    if args.command == "update-spec":
        return cmd_update_spec(args)
    if args.command == "finish-spec":
        return cmd_finish_spec(args)
    if args.command == "render-user-story-docs":
        return cmd_render_user_story_docs(args)
    if args.command == "sync-plan-branches":
        return cmd_sync_plan_branches(args)
    if args.command == "check-scope-drift":
        return cmd_check_scope_drift(args)
    if args.command == "render-message":
        return cmd_render_message(args)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
