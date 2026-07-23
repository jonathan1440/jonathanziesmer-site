"""Fetch GitHub Project v2 items via GraphQL, paged."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from diff import normalize_issue_type, normalize_status, task_sub_issue_count

_SCRIPT_DIR = Path(__file__).resolve().parent
_GH_SCRIPTS_DIR = _SCRIPT_DIR.parent / "gh"


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


PROJECT_ITEMS_QUERY = """
query($owner: String!, $number: Int!, $cursor: String) {
  organizationOrUser: repositoryOwner(login: $owner) {
    ... on ProjectV2Owner {
      projectV2(number: $number) {
        items(first: 100, after: $cursor) {
          pageInfo { hasNextPage endCursor }
          nodes {
            id
            fieldValueByName(name: "Status") {
              ... on ProjectV2ItemFieldSingleSelectValue { name }
            }
            content {
              ... on Issue {
                number
                title
                url
                state
                issueType { name }
                trackedIssues { totalCount }
                parent { number }
                repository { nameWithOwner }
              }
            }
          }
        }
      }
    }
  }
}
"""


def fetch_project_items(owner: str, number: int, *, graphql_fn=None) -> list[dict[str, Any]]:
    """Page through the Project v2 board `owner`/`number` and normalize items.

    Returns a list of dicts:
    {issue, repo, number, url, title, status, issue_type, parent_number,
     task_sub_issue_count, item_id}
    """
    if graphql_fn is None:
        module = _load_gh_spec_publish()
        graphql_fn = module.graphql_with_features

    number = int(number)

    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        result = graphql_fn(
            PROJECT_ITEMS_QUERY,
            {"owner": owner, "number": number, "cursor": cursor},
        )
        project = (
            result.get("data", {}).get("organizationOrUser", {}).get("projectV2") or {}
        )
        node_list = project.get("items") or {}
        nodes = node_list.get("nodes") or []
        for node in nodes:
            content = node.get("content") or {}
            if not content or "number" not in content:
                continue
            repo = (content.get("repository") or {}).get("nameWithOwner")
            issue_number = content.get("number")
            status_field = node.get("fieldValueByName") or {}
            parent = content.get("parent") or {}
            items.append(
                {
                    "issue": f"{repo}#{issue_number}",
                    "repo": repo,
                    "number": issue_number,
                    "url": content.get("url"),
                    "title": content.get("title"),
                    "status": normalize_status(status_field.get("name")),
                    "issue_type": normalize_issue_type(
                        (content.get("issueType") or {}).get("name")
                    ),
                    "parent_number": parent.get("number"),
                    "task_sub_issue_count": task_sub_issue_count(content),
                    "item_id": node.get("id"),
                }
            )
        page_info = node_list.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    return items
