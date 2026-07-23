"""Poll merged PRs and classify them as task/spec chain-trigger events (Phase 3)."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_GH_SCRIPTS_DIR = _SCRIPT_DIR.parent / "gh"

MERGED_PRS_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: MERGED, first: 50, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        url
        title
        body
        mergedAt
        headRefName
        closingIssuesReferences(first: 10) {
          nodes { number repository { nameWithOwner } }
        }
      }
    }
  }
}
"""

_CLOSES_PATTERN = re.compile(
    r"(?:closes|fixes|resolves)\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#\d+)",
    re.IGNORECASE,
)


def _load_gh_spec_publish():
    module_name = "gh_spec_publish_for_auto"
    if module_name in sys.modules:
        return sys.modules[module_name]
    path = _GH_SCRIPTS_DIR / "gh-spec-publish.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def classify_head_ref(head_ref: str | None) -> str | None:
    """Return 'task' or 'spec' for the harness's branch-naming convention, else None."""
    if not head_ref:
        return None
    if head_ref.startswith("task/"):
        return "task"
    if head_ref.startswith("spec/"):
        return "spec"
    return None


def parse_closes_from_body(body: str | None) -> list[str]:
    """Extract `owner/repo#N` refs from Closes/Fixes/Resolves lines in a PR body."""
    if not body:
        return []
    seen: dict[str, None] = {}
    for match in _CLOSES_PATTERN.finditer(body):
        seen.setdefault(match.group(1), None)
    return list(seen)


def pr_key(repo: str, number: int) -> str:
    """Format a repo + number as the canonical `owner/repo#N` reference string."""
    return f"{repo}#{number}"


def _default_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    module = _load_gh_spec_publish()
    return module.graphql_with_features(query, variables)


def fetch_merged_prs(
    repo: str,
    *,
    lookback_hours: float = 72,
    graphql_fn=None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Page through merged PRs on `repo`, keeping task/* and spec/* branches
    merged within `lookback_hours`.

    Returns events: {kind, pr, url, head_ref, closing_issues, merged_at,
    title, repo, number}. `pr` and each `closing_issues` entry are
    `"owner/repo#N"` strings; `number` is the raw PR number on `repo`.
    """
    graphql_fn = graphql_fn or _default_graphql
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback_hours)
    owner, name = repo.split("/", 1)

    events: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        result = graphql_fn(MERGED_PRS_QUERY, {"owner": owner, "name": name, "cursor": cursor})
        pr_conn = result.get("data", {}).get("repository", {}).get("pullRequests") or {}
        nodes = pr_conn.get("nodes") or []
        for node in nodes:
            head_ref = node.get("headRefName")
            prefix = classify_head_ref(head_ref)
            if prefix is None:
                continue

            merged_at_raw = node.get("mergedAt")
            if not merged_at_raw:
                continue
            merged_at = datetime.fromisoformat(merged_at_raw.replace("Z", "+00:00"))
            if merged_at < cutoff:
                continue

            closing_nodes = (node.get("closingIssuesReferences") or {}).get("nodes") or []
            closing_issues = [
                pr_key(n["repository"]["nameWithOwner"], n["number"])
                for n in closing_nodes
                if n.get("repository")
            ]
            if not closing_issues:
                closing_issues = parse_closes_from_body(node.get("body"))

            kind = "task_pr_merged" if prefix == "task" else "spec_pr_merged"
            events.append(
                {
                    "kind": kind,
                    "pr": pr_key(repo, node["number"]),
                    "url": node.get("url"),
                    "head_ref": head_ref,
                    "closing_issues": closing_issues,
                    "merged_at": merged_at_raw,
                    "title": node.get("title"),
                    "repo": repo,
                    "number": node["number"],
                }
            )

        page_info = pr_conn.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    return events


def diff_merged_prs(
    previous_keys,
    current_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return events not present in `previous_keys`, sorted oldest-merged first."""
    previous = set(previous_keys)
    unseen = [ev for ev in current_events if pr_key(ev["repo"], ev["number"]) not in previous]
    unseen.sort(key=lambda ev: ev["merged_at"])
    return unseen


def load_merged_snapshot(path: Path | str) -> list[str]:
    p = Path(path)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        return []
    return list(data.get("prs", []))


def save_merged_snapshot(path: Path | str, keys) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"prs": sorted(set(keys))}, indent=2))
