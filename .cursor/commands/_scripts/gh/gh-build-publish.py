#!/usr/bin/env python3
"""
GitHub task build automation for /gh-build.

Usage:
  gh-build-publish.py preflight
  gh-build-publish.py context --issue OWNER/REPO#N | URL [-o PATH] [--state-dir DIR]
  gh-build-publish.py prepare --issue REF [--sync-story] [--state-dir DIR]
  gh-build-publish.py start --issue REF [-o PATH] [--state-dir DIR]
  gh-build-publish.py checkout --issue REF [--repo-path PATH] [--dry-run] [--state-dir DIR]
  gh-build-publish.py verify --input CONTEXT.json [--repo-path PATH] [--state-dir DIR]
  gh-build-publish.py gates --input CONTEXT.json [--require-verify] [--state-dir DIR]
  gh-build-publish.py commit-push --input CONTEXT.json [--state-dir DIR]
  gh-build-publish.py finalize --input CONTEXT.json --ac-attested [--state-dir DIR]
  gh-build-publish.py finish --input CONTEXT.json [--state-dir DIR]
  gh-build-publish.py report --input CONTEXT.json [--state-dir DIR]
  gh-build-publish.py bootstrap-harness --repo-path PATH [-o PATH]

Use --state-dir to write/read predictable step JSON files (context.json, checkout.json, …).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_COMMANDS_ROOT = _SCRIPT_DIR.parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from gh_plan_parsers import parse_scope_files, section_text

TEMPLATE_DIR = _COMMANDS_ROOT / "_templates" / "repo-testing"
HARNESS_SCRIPT_PATHS = (
    "scripts/test-tier1-lint.sh",
    "scripts/test-tier2-unit.sh",
    "scripts/test-tier3-security.sh",
    "scripts/test-tier4-integration.sh",
    "scripts/test-tier5-multiservice.sh",
    "scripts/test-tier6-product.sh",
    "scripts/test-tier7-monitor.sh",
    "scripts/test-tiers.sh",
    "scripts/test-tiers-12.sh",
)
HARNESS_SUPPORT_PATHS = (
    "tests/test_smoke.py",
    "tests/conftest.py",
)
TIER_VERIFY_ENTRIES = (
    ("tier1", "scripts/test-tier1-lint.sh"),
    ("tier2", "scripts/test-tier2-unit.sh"),
    ("tier3", "scripts/test-tier3-security.sh"),
    ("tier4", "scripts/test-tier4-integration.sh"),
)
# Tiers whose scripts report exit 2 = SKIP (no tooling/surface) rather than failure.
SKIPPABLE_TIERS = frozenset({"tier3", "tier4"})
_SPEC_PUBLISH_PATH = _SCRIPT_DIR / "gh-spec-publish.py"

_spec = importlib.util.spec_from_file_location("gh_spec_publish", _SPEC_PUBLISH_PATH)
assert _spec and _spec.loader
_gsp = importlib.util.module_from_spec(_spec)
sys.modules["gh_spec_publish"] = _gsp
_spec.loader.exec_module(_gsp)

default_branch = _gsp.default_branch
edit_issue = _gsp.edit_issue
find_project_item_id = _gsp.find_project_item_id
gh_json = _gsp.gh_json
gh_run = _gsp.gh_run
issue_ref = _gsp.issue_ref
link_issue_branch = _gsp.link_issue_branch
linked_branches = _gsp.linked_branches
linked_branches_supported = _gsp.linked_branches_supported
load_manifest = _gsp.load_manifest
parse_issue_url = _gsp.parse_issue_url
parse_repo = _gsp.parse_repo
remote_branch_exists = _gsp.remote_branch_exists
resolve_project_config = _gsp.resolve_project_config
resolve_task_branch_base = _gsp.resolve_task_branch_base
save_manifest = _gsp.save_manifest
slugify_story_title = _gsp.slugify_story_title
task_branch_name = _gsp.task_branch_name
graphql = _gsp.graphql

ISSUE_PROJECT_ITEMS_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      projectItems(first: 20) {
        nodes {
          id
          project {
            id
            number
            title
            owner {
              ... on User { login }
              ... on Organization { login }
            }
          }
        }
      }
    }
  }
}
"""

UPDATE_PROJECT_STATUS_MUTATION = """
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $projectId
    itemId: $itemId
    fieldId: $fieldId
    value: { singleSelectOptionId: $optionId }
  }) {
    projectV2Item { id }
  }
}
"""

ISSUE_SPEC_PATTERN = re.compile(
    r"^(?:https://github\.com/)?(?P<owner>[^/#]+)/(?P<repo>[^/#]+)#(?P<number>\d+)$"
)
STORY_LINE_PATTERN = re.compile(
    r"Story:\s*\**\s*([A-Z]{2}-\d+)\s*\**\s*.*?\(\s*#\s*(\d+)\s*\)",
    re.IGNORECASE,
)
ACCEPTANCE_PATTERN = re.compile(
    r"Acceptance:\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
BLOCKED_BY_PATTERN = re.compile(
    r"Blocked by:\s*(.+)$",
    re.IGNORECASE,
)
BACKTICK_PATH_PATTERN = re.compile(r"`([^`]+)`")
VERIFY_PATTERN = re.compile(r"Verify:\s*`([^`]+)`", re.IGNORECASE)
TEST_FILE_PATTERN = re.compile(
    r"(?:Add/update|Test file|Tests?):\s*`([^`]+)`",
    re.IGNORECASE,
)
AC_HEADING_PATTERN = re.compile(r"^###\s+(AC-\d+)\s*[—\-]", re.IGNORECASE | re.MULTILINE)
DEV_BRANCH_SECTION = re.compile(r"^##\s+Development branch\s*$", re.IGNORECASE | re.MULTILINE)
DEV_BRANCH_BACKTICK = re.compile(r"## Development branch\s*\n+\s*`([^`]+)`", re.IGNORECASE)

STATUS_PATTERNS: dict[str, re.Pattern[str]] = {
    "in_progress": re.compile(r"^In[ -]?[Pp]rogress$"),
    "review_qa": re.compile(r"^Review\s*/?\s*[Qq][Aa]$"),
    "todo": re.compile(r"^To[ -]?[Dd]o$"),
    "ready_to_ship": re.compile(r"^Ready\s+to\s+[Ss]hip$"),
}
CLOSING_KEYWORD_PATTERN = re.compile(
    r"(?i)\b(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\b"
)

BUG_KEYWORDS = ("fix", "regression", "repro", "broken", "bug")
UI_SCOPE_EXTENSIONS = {".tsx", ".jsx", ".vue", ".css", ".scss", ".html"}
FORBIDDEN_BRANCH_PREFIXES = ("spec/", "user-story/")

STATE_FILES: dict[str, str] = {
    "context": "context.json",
    "checkout": "checkout.json",
    "verify": "verify.json",
    "gates": "gates.json",
    "commit": "commit.json",
    "finish": "finish.json",
    "report": "report.json",
}

MIN_GH_VERSION = (2, 40)


def task_issue_link_keyword(task_repo: str, task_number: int) -> str:
    """GitHub PR body keyword that links (and closes on merge) the task issue."""
    return f"Closes {task_repo}#{task_number}"


def pr_body_links_task_issue(body: str, task_repo: str, task_number: int) -> bool:
    if CLOSING_KEYWORD_PATTERN.search(body) and (
        re.search(rf"(?<![\w/])#{task_number}\b", body)
        or re.search(
            rf"{re.escape(task_repo)}#\s*{task_number}\b",
            body,
            re.IGNORECASE,
        )
    ):
        return True
    return False


def render_pr_body(ctx: dict[str, Any]) -> str:
    story = ctx["story_issue"]
    task = ctx["task_issue"]
    task_repo = ctx["repository"]
    ac_list = ", ".join(ctx.get("ac_ids") or [])
    link_line = task_issue_link_keyword(task_repo, int(task["number"]))
    traceability_lines = [f"- Task: {task_repo}#{task['number']}"]
    if story:
        traceability_lines.append(f"- Story: {story['repo']}#{story['number']} ({story['id']})")
        traceability_lines.append(f"- AC: {ac_list}")
    else:
        traceability_lines.append("- Story: none (standalone bug)")
    return "\n".join(
        [
            link_line,
            "",
            "## Summary",
            ctx.get("task_summary") or "Task implementation",
            "",
            "## Traceability",
            *traceability_lines,
            "",
            "## Test plan",
            f"- [x] `{ctx.get('verify_cmd', '')}`",
            "",
        ]
    )


def ensure_pr_links_task_issue(
    task_repo: str,
    pr_number: int,
    task_number: int,
) -> dict[str, Any]:
    data = gh_json(
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            task_repo,
            "--json",
            "body,url",
        ]
    )
    body = data.get("body") or ""
    if pr_body_links_task_issue(body, task_repo, task_number):
        return {
            "linked": True,
            "action": "already_linked",
            "url": data.get("url"),
        }
    link_line = task_issue_link_keyword(task_repo, task_number)
    new_body = body.rstrip() + f"\n\n{link_line}\n"
    gh_run(
        [
            "pr",
            "edit",
            str(pr_number),
            "--repo",
            task_repo,
            "--body",
            new_body,
        ]
    )
    return {
        "linked": True,
        "action": "updated_body",
        "url": data.get("url"),
        "link_keyword": link_line,
    }


def task_branch_link_base(ctx: dict[str, Any]) -> str:
    parent = ctx["parent_branch"]
    parent_branch = parent.get("branch")
    if parent_branch and parent.get("exists_on_remote"):
        return parent_branch
    manifest = (
        load_manifest(Path(ctx["manifest_path"])) if ctx.get("manifest_path") else {}
    )
    return resolve_task_branch_base(
        ctx["repository"],
        manifest,
        ctx["story_issue"]["id"],
    )


def ensure_task_branch_linked(ctx: dict[str, Any]) -> dict[str, Any]:
    """Link task branch to task issue via gh issue develop (Development sidebar)."""
    task_repo = ctx["repository"]
    task_number = int(ctx["task_issue"]["number"])
    task_branch = ctx["task_branch"]["branch"]
    if task_branch in linked_branches(task_repo, task_number):
        return {
            "linked": True,
            "action": "already_linked",
            "branch": task_branch,
        }
    if not linked_branches_supported():
        return {
            "linked": False,
            "action": "skipped",
            "reason": "gh issue develop unavailable",
            "branch": task_branch,
        }
    base = task_branch_link_base(ctx)
    link_issue_branch(
        task_repo,
        task_number,
        task_branch,
        base,
        enabled=True,
    )
    if task_branch in linked_branches(task_repo, task_number):
        return {
            "linked": True,
            "action": "linked",
            "branch": task_branch,
            "base": base,
        }
    return {
        "linked": False,
        "action": "link_failed",
        "branch": task_branch,
        "base": base,
    }


def parse_issue_spec(value: str, default_repo: str | None = None) -> tuple[str, int]:
    value = value.strip()
    parsed = parse_issue_url(value)
    if parsed:
        return parsed
    match = ISSUE_SPEC_PATTERN.match(value)
    if match:
        repo = f"{match.group('owner')}/{match.group('repo')}"
        return repo, int(match.group("number"))
    if value.isdigit():
        if not default_repo:
            raise SystemExit(f"issue number {value} requires --repo OWNER/NAME")
        return default_repo, int(value)
    raise SystemExit(f"cannot parse issue reference: {value!r}")


def write_json(path: str | None, data: dict[str, Any]) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if path:
        Path(path).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def state_file_path(state_dir: Path, key: str) -> str:
    return str(state_dir / STATE_FILES[key])


def add_state_dir_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--state-dir",
        help="Directory for step JSON files (context.json, verify.json, …)",
    )


def apply_state_dir_defaults(args: argparse.Namespace) -> None:
    state_dir = getattr(args, "state_dir", None)
    if not state_dir:
        return
    sd = Path(state_dir)
    sd.mkdir(parents=True, exist_ok=True)
    cmd = args.command

    input_commands = {
        "verify",
        "gates",
        "commit-push",
        "finish",
        "report",
        "finalize",
        "open-pr",
    }
    if cmd in input_commands and not getattr(args, "input", None):
        args.input = state_file_path(sd, "context")

    output_key_by_command = {
        "context": "context",
        "start": "context",
        "prepare": "context",
        "checkout": "checkout",
        "verify": "verify",
        "gates": "gates",
        "commit-push": "commit",
        "finish": "finish",
        "report": "report",
        "finalize": "report",
    }
    if not getattr(args, "output", None) and cmd in output_key_by_command:
        args.output = state_file_path(sd, output_key_by_command[cmd])

    if cmd in {"gates", "commit-push", "finalize"} and not getattr(args, "verify_result", None):
        verify_path = sd / STATE_FILES["verify"]
        if verify_path.exists() or cmd in {"commit-push", "finalize"}:
            args.verify_result = str(verify_path)

    if cmd == "report":
        for attr, key in (
            ("checkout", "checkout"),
            ("verify_json", "verify"),
            ("gates_json", "gates"),
            ("commit", "commit"),
            ("finish", "finish"),
        ):
            if not getattr(args, attr, None):
                path = sd / STATE_FILES[key]
                if path.exists() or key in {"checkout", "verify", "gates", "commit", "finish"}:
                    setattr(args, attr, str(path))


def gh_version_ok() -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return False, str(exc)
    first_line = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else "gh unknown"
    match = re.search(r"gh version (\d+)\.(\d+)", first_line)
    if not match:
        return False, first_line
    version = (int(match.group(1)), int(match.group(2)))
    if version < MIN_GH_VERSION:
        return False, f"{first_line} (need >= {MIN_GH_VERSION[0]}.{MIN_GH_VERSION[1]})"
    return True, first_line


def parse_repository(body: str) -> str:
    text = section_text(body, "## Repository")
    match = BACKTICK_PATH_PATTERN.search(text)
    if match and "/" in match.group(1):
        return match.group(1).strip()
    for line in text.splitlines():
        line = line.strip()
        if "/" in line and not line.startswith("|"):
            return line.strip("` ")
    raise SystemExit("task issue missing ## Repository (owner/repo)")


def parse_traceability(body: str) -> dict[str, Any]:
    text = section_text(body, "## Traceability")
    story_match = STORY_LINE_PATTERN.search(text)
    if not story_match:
        # No parent story — standalone issue (e.g. a bare bug report). Build
        # against the repo default branch instead of a story branch.
        return {"story_id": None, "story_number": None, "ac_ids": [], "ac_raw": ""}
    story_id = story_match.group(1).upper()
    story_number = int(story_match.group(2))
    ac_match = ACCEPTANCE_PATTERN.search(text)
    ac_raw = ac_match.group(1).strip() if ac_match else ""
    ac_raw = re.sub(r"[*_`]", "", ac_raw)
    ac_ids = [
        token.strip().upper()
        for token in re.split(r"[,;]", ac_raw)
        if re.match(r"^AC-\d+$", token.strip(), re.IGNORECASE)
    ]
    return {
        "story_id": story_id,
        "story_number": story_number,
        "ac_ids": ac_ids,
        "ac_raw": ac_raw,
    }


def parse_development_branch(body: str) -> str | None:
    match = DEV_BRANCH_BACKTICK.search(body)
    if match:
        return match.group(1).strip()
    text = section_text(body, "## Development branch")
    match = BACKTICK_PATH_PATTERN.search(text)
    return match.group(1).strip() if match else None


def parse_tests(body: str) -> dict[str, Any]:
    text = section_text(body, "## Tests")
    if not text:
        raise SystemExit("task issue missing ## Tests")
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
    if not verify_cmd:
        raise SystemExit("task issue ## Tests missing Verify: command")
    return {"verify_cmd": verify_cmd, "test_files": test_files}


def parse_patterns(body: str) -> list[str]:
    text = section_text(body, "## Patterns")
    patterns: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            patterns.append(line[2:].strip())
    return patterns


def parse_decisions(body: str) -> list[str]:
    text = section_text(body, "## Decisions")
    decisions: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            decisions.append(line[2:].strip())
    return decisions


def parse_blockers(body: str) -> list[dict[str, str]]:
    text = section_text(body, "## Dependencies")
    blockers: list[dict[str, str]] = []
    for line in text.splitlines():
        match = BLOCKED_BY_PATTERN.search(line)
        if not match:
            continue
        value = match.group(1).strip()
        if value.lower() in ("none", "n/a", ""):
            continue
        issue_match = re.search(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)", value)
        if issue_match:
            blockers.append(
                {
                    "repo": issue_match.group(1),
                    "number": issue_match.group(2),
                    "raw": value,
                }
            )
    return blockers


def parse_spec_path(body: str) -> str | None:
    for pattern in (
        r"`(docs/specs/[^`\s]+/SPEC\.md)`",
        r"(docs/specs/[^\s)]+/SPEC\.md)",
        r"Spec file:\s*`([^`]+)`",
    ):
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def parse_development_branches_table(body: str) -> list[dict[str, str]]:
    branches: list[dict[str, str]] = []
    in_section = False
    for line in body.splitlines():
        if re.match(r"^##\s+Development branches", line, re.IGNORECASE):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section or not line.strip().startswith("|"):
            continue
        if re.match(r"^\|\s*-+", line):
            continue
        if "repo" in line.lower() and "branch" in line.lower():
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        repo = cells[0].strip("` ")
        branch = cells[1].strip("` ")
        if "/" in repo and branch:
            entry: dict[str, str] = {"repo": repo, "branch": branch}
            if len(cells) > 2:
                base = cells[2].strip("` ")
                if base:
                    entry["base"] = base
            branches.append(entry)
    return branches


def parse_task_body(body: str) -> dict[str, Any]:
    trace = parse_traceability(body)
    tests = parse_tests(body)
    return {
        "task_summary": section_text(body, "## Task"),
        "repository": parse_repository(body),
        "traceability": trace,
        "development_branch": parse_development_branch(body),
        "scope_files": parse_scope_files(body),
        "test_files": tests["test_files"],
        "verify_cmd": tests["verify_cmd"],
        "patterns": parse_patterns(body),
        "decisions": parse_decisions(body),
        "blockers": parse_blockers(body),
        "spec_path": parse_spec_path(body),
        "story_id": trace["story_id"],
        "story_number": trace["story_number"],
        "ac_ids": trace["ac_ids"],
    }


def workspace_roots_from_args(args: argparse.Namespace) -> list[Path]:
    roots = [Path(p).resolve() for p in (args.workspace_root or [])]
    repo_path = getattr(args, "repo_path", None)
    if repo_path:
        roots.insert(0, Path(repo_path).resolve())
    if not roots:
        cwd = Path.cwd().resolve()
        roots = [cwd, cwd.parent]
    git_root = git_toplevel(roots[0])
    if git_root and git_root not in roots:
        roots.insert(0, git_root)
    return roots


def git_toplevel(start: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None
    path = Path(result.stdout.strip())
    return path if path.is_dir() else None


def origin_remote_url(repo_path: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return None


def remote_matches_repo(remote: str, owner: str, name: str) -> bool:
    normalized = remote.removesuffix(".git")
    if f"{owner}/{name}" in normalized:
        return True
    return normalized.endswith(f"/{name}")


def find_local_repo_path(task_repo: str, roots: list[Path]) -> str | None:
    owner, name = parse_repo(task_repo)
    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        toplevel = git_toplevel(root)
        if toplevel and toplevel.name == name and toplevel not in seen:
            candidates.append(toplevel)
            seen.add(toplevel)
        direct = root / name
        if direct.is_dir() and direct not in seen:
            candidates.append(direct)
            seen.add(direct)
        try:
            for child in root.iterdir():
                if child.is_dir() and child.name == name and child not in seen:
                    candidates.append(child)
                    seen.add(child)
        except OSError:
            continue

    exact: list[Path] = []
    by_name: list[Path] = []
    for path in candidates:
        if not (path / ".git").exists():
            continue
        remote = origin_remote_url(path)
        if not remote:
            continue
        if remote_matches_repo(remote, owner, name):
            exact.append(path)
        elif name in remote:
            by_name.append(path)

    if len(exact) == 1:
        return str(exact[0])
    if len(exact) > 1:
        raise SystemExit(
            f"ambiguous local checkout for {task_repo}: "
            + ", ".join(str(p) for p in exact)
        )
    if len(by_name) == 1:
        return str(by_name[0])
    if len(by_name) > 1:
        raise SystemExit(
            f"ambiguous local checkout for {task_repo} (fork/name match): "
            + ", ".join(str(p) for p in by_name)
        )
    return None


def find_manifest_path(
    spec_path: str | None,
    local_repo_path: str | None,
) -> Path | None:
    if not spec_path or not local_repo_path:
        return None
    candidate = Path(local_repo_path) / spec_path.replace("SPEC.md", "gh-spec.manifest.json")
    return candidate if candidate.exists() else None


def find_manifest_in_roots(roots: list[Path]) -> Path | None:
    seen: set[Path] = set()
    for root in roots:
        search_roots = [root]
        toplevel = git_toplevel(root)
        if toplevel:
            search_roots.append(toplevel)
        for base in search_roots:
            if not base.is_dir() or base in seen:
                continue
            seen.add(base)
            direct = base / "docs/specs/knowledge-graph-v1/gh-spec.manifest.json"
            if direct.exists():
                return direct
            try:
                for candidate in base.glob("docs/specs/*/gh-spec.manifest.json"):
                    if candidate.exists():
                        return candidate
            except OSError:
                continue
    return None


def infer_build_hints(
    *,
    task_summary: str,
    scope_files: list[str],
    title: str,
) -> dict[str, Any]:
    text = f"{title} {task_summary}".lower()
    is_bug = any(word in text for word in BUG_KEYWORDS)
    browser = any(Path(path).suffix in UI_SCOPE_EXTENSIONS for path in scope_files)
    return {
        "task_kind": "bug" if is_bug else "feature",
        "tdd_mode": "prove_it" if is_bug else "red_green_refactor",
        "browser_verify_required": browser,
    }


def package_inits_for_scope(scope_file: str) -> list[str]:
    inits: list[str] = []
    current = Path(scope_file).parent
    while current.parts and current != Path("."):
        init = current / "__init__.py"
        if init.exists():
            inits.append(init.as_posix())
        if current.name == "src":
            break
        current = current.parent
    return inits


def git_path_changed(repo_path: str, rel_path: str) -> bool:
    result = git_run(["status", "--porcelain", "--", rel_path], repo_path, check=False)
    return bool(result.stdout.strip())


def harness_paths_for_repo(repo_path: str) -> set[str]:
    root = Path(repo_path)
    paths: set[str] = set()
    for rel in (*HARNESS_SCRIPT_PATHS, *HARNESS_SUPPORT_PATHS):
        if (root / rel).exists():
            paths.add(rel)
    return paths


def repo_has_python_tests(root: Path) -> bool:
    skip_dirs = {".venv", ".git", "node_modules", "__pycache__"}
    for pattern in ("test_*.py", "*_test.py"):
        for path in root.rglob(pattern):
            if any(part in skip_dirs for part in path.parts):
                continue
            return True
    return False


def maybe_scaffold_pytest_smoke(repo_path: str, created: list[str]) -> None:
    root = Path(repo_path)
    if not (root / "pyproject.toml").exists():
        return
    if repo_has_python_tests(root):
        return
    dest = root / "tests" / "test_smoke.py"
    if dest.exists():
        return
    template = TEMPLATE_DIR / "test_smoke.py"
    if not template.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, dest)
    created.append("tests/test_smoke.py")


def ensure_test_harness(repo_path: str) -> dict[str, Any]:
    root = Path(repo_path)
    created: list[str] = []
    for rel in HARNESS_SCRIPT_PATHS:
        dest = root / rel
        if dest.exists():
            continue
        src = TEMPLATE_DIR / Path(rel).name
        if not src.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        dest.chmod(dest.stat().st_mode | 0o111)
        created.append(rel)
    maybe_scaffold_pytest_smoke(repo_path, created)
    return {"bootstrapped": bool(created), "created": created}


def tier_scripts_present(repo_path: str) -> bool:
    root = Path(repo_path)
    return any((root / rel).exists() for _, rel in TIER_VERIFY_ENTRIES)


def summarize_tier_result(entry: dict[str, Any]) -> str:
    if entry.get("skipped"):
        return "skipped"
    if entry.get("exit_code") == 0:
        return "pass"
    if entry.get("harness_missing"):
        return "harness_missing"
    return "fail"


def collect_commit_files(ctx: dict[str, Any], repo_path: str) -> list[str]:
    files = list(dict.fromkeys(ctx.get("scope_files", []) + ctx.get("test_files", [])))
    for scope_file in ctx.get("scope_files", []):
        for init_path in package_inits_for_scope(scope_file):
            if init_path not in files and git_path_changed(repo_path, init_path):
                files.append(init_path)
    for path in sorted(harness_paths_for_repo(repo_path)):
        if path not in files and git_path_changed(repo_path, path):
            files.append(path)
    return files


def git_changed_paths(repo_path: str) -> set[str]:
    result = git_run(["status", "--porcelain"], repo_path, check=False)
    paths: set[str] = set()
    for line in result.stdout.splitlines():
        if len(line) >= 4:
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            paths.add(path)
    return paths


def allowed_scope_paths(ctx: dict[str, Any], repo_path: str) -> set[str]:
    allowed = set(ctx.get("scope_files", []) + ctx.get("test_files", []))
    for scope_file in ctx.get("scope_files", []):
        allowed.update(package_inits_for_scope(scope_file))
    allowed.update(harness_paths_for_repo(repo_path))
    return allowed


def is_forbidden_branch(branch: str) -> bool:
    if branch in ("main", "master"):
        return True
    return any(branch.startswith(prefix) for prefix in FORBIDDEN_BRANCH_PREFIXES)


def detect_suite_command(repo_path: Path) -> str | None:
    if (repo_path / "pyproject.toml").exists():
        return "pytest -q"
    package_json = repo_path / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if data.get("scripts", {}).get("test"):
            return "npm test"
    return None


def uses_uv_project(repo_path: Path | str) -> bool:
    return (Path(repo_path) / "uv.lock").exists()


def wrap_tool_command(command: str, repo_path: Path | str) -> str:
    """Prefix with ``uv run`` when uv.lock exists and command is a Python tool."""
    stripped = command.strip()
    if not stripped or not uses_uv_project(repo_path):
        return stripped
    if stripped.startswith("uv run ") or stripped.startswith("uv "):
        return stripped
    if any(ch in stripped for ch in ("|", "&&", ";")):
        return stripped
    first = stripped.split()[0]
    if first in ("pytest", "ruff"):
        return f"uv run {stripped}"
    return stripped


def detect_build_command(repo_path: Path) -> str | None:
    package_json = repo_path / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if data.get("scripts", {}).get("build"):
            return "npm run build"
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        try:
            text = pyproject.read_text(encoding="utf-8")
        except OSError:
            text = ""
        if (repo_path / "ruff.toml").exists() or "[tool.ruff" in text:
            return "ruff check ."
    return None


def run_shell_step(command: str, cwd: str, *, wrap_uv: bool = True) -> dict[str, Any]:
    effective = wrap_tool_command(command, cwd) if wrap_uv else command
    result = subprocess.run(
        effective,
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    tail = combined[-4000:] if combined else ""
    return {
        "command": effective,
        "exit_code": result.returncode,
        "output_tail": tail,
    }


def run_verify(ctx: dict[str, Any], repo_path: str) -> dict[str, Any]:
    verify_cmd = (ctx.get("verify_cmd") or "").strip()
    if not verify_cmd:
        return {"ok": False, "error": "missing verify_cmd in context"}

    ok = True
    output: dict[str, Any] = {"tiers": {}}
    repo = Path(repo_path)
    has_tiers = tier_scripts_present(repo_path)

    failed_tier: str | None = None
    for name, rel in TIER_VERIFY_ENTRIES:
        if failed_tier:
            output["tiers"][name] = {"skipped": True, "reason": f"{failed_tier} failed first"}
            continue
        if (repo / rel).exists():
            result = run_shell_step(f"bash {rel}", repo_path, wrap_uv=False)
            if name == "tier2" and result["exit_code"] == 2:
                tail = result.get("output_tail") or ""
                if "tier2: SKIP" in tail:
                    result["harness_missing"] = True
            if name in SKIPPABLE_TIERS and result["exit_code"] == 2:
                result["skipped"] = True
                result["reason"] = "tier reported SKIP (exit 2)"
            output["tiers"][name] = result
            tier_ok = result["exit_code"] == 0 or bool(result.get("skipped"))
            ok = ok and tier_ok
            if not tier_ok:
                # Outline §3: run tiers in order, stop at the first failure.
                failed_tier = name
        else:
            output["tiers"][name] = {"skipped": True, "reason": f"missing {rel}"}

    verify_result = run_shell_step(verify_cmd, repo_path)
    output["verify_cmd"] = verify_result
    ok = ok and verify_result["exit_code"] == 0

    if has_tiers:
        output["suite"] = {"skipped": True, "reason": "tier scripts present"}
        output["build"] = {"skipped": True, "reason": "tier scripts present"}
    else:
        suite_cmd = detect_suite_command(repo)
        if suite_cmd and suite_cmd != verify_cmd:
            suite_result = run_shell_step(suite_cmd, repo_path)
            output["suite"] = suite_result
            ok = ok and suite_result["exit_code"] == 0
        else:
            output["suite"] = {
                "skipped": True,
                "reason": "same as verify_cmd" if suite_cmd == verify_cmd else "no suite command detected",
            }

        build_cmd = detect_build_command(repo)
        if build_cmd:
            build_result = run_shell_step(build_cmd, repo_path)
            output["build"] = build_result
            ok = ok and build_result["exit_code"] == 0
        else:
            output["build"] = {"skipped": True, "reason": "no build command detected"}

    output["ok"] = ok
    return output


def run_gates(
    ctx: dict[str, Any],
    repo_path: str,
    *,
    require_verify: bool = False,
    verify_result: dict[str, Any] | None = None,
    allow_out_of_scope: bool = False,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    blocker_ok = bool(ctx.get("blocker_gate", {}).get("passed"))
    checks.append({"name": "blocker_gate", "ok": blocker_ok})

    current = git_run(["branch", "--show-current"], repo_path).stdout.strip()
    expected = ctx.get("task_branch", {}).get("branch")
    task_branch_ok = current == expected
    checks.append(
        {
            "name": "task_branch",
            "ok": task_branch_ok,
            "detail": f"on {current!r}, expected {expected!r}" if not task_branch_ok else None,
        }
    )

    forbidden_ok = not is_forbidden_branch(current)
    checks.append(
        {
            "name": "not_story_or_main",
            "ok": forbidden_ok,
            "detail": f"forbidden branch {current!r}" if not forbidden_ok else None,
        }
    )

    changed = git_changed_paths(repo_path)
    allowed = allowed_scope_paths(ctx, repo_path)
    out_of_scope = sorted(path for path in changed if path not in allowed)
    scope_ok = allow_out_of_scope or not out_of_scope
    checks.append(
        {
            "name": "scope_discipline",
            "ok": scope_ok,
            "detail": ", ".join(out_of_scope) if out_of_scope else None,
        }
    )

    if require_verify:
        if verify_result is None:
            verify_result = run_verify(ctx, repo_path)
        verify_ok = bool(verify_result.get("ok"))
        checks.append(
            {
                "name": "verify",
                "ok": verify_ok,
                "detail": verify_result.get("error"),
            }
        )

    ok = all(check["ok"] for check in checks)
    return {"ok": ok, "checks": checks}


def start_exit_code(status_update: dict[str, Any], strict: bool) -> int:
    if not strict:
        return 0
    return 0 if status_update.get("ok") else 1


def finish_exit_code(
    pr_result: dict[str, Any],
    status_update: dict[str, Any],
    strict: bool,
) -> int:
    if not strict:
        return 0
    if not pr_result.get("ok") and not pr_result.get("skipped"):
        return 1
    if not status_update.get("ok"):
        return 1
    return 0


def sync_story_branch(
    repo_path: str,
    *,
    parent_branch: str | None,
    created: bool,
) -> dict[str, Any]:
    if created or not parent_branch:
        return {"action": "skipped", "detail": "new branch or no parent branch"}

    git_run(["fetch", "origin", parent_branch], repo_path)
    ahead = git_run(
        ["rev-list", "--count", f"origin/{parent_branch}..HEAD"],
        repo_path,
        check=False,
    ).stdout.strip()
    behind = git_run(
        ["rev-list", "--count", f"HEAD..origin/{parent_branch}"],
        repo_path,
        check=False,
    ).stdout.strip()
    unique_commits = int(ahead or "0")
    behind_commits = int(behind or "0")

    if unique_commits > 0 and behind_commits > 0:
        return {
            "action": "needed",
            "detail": "task branch behind story; has local commits",
            "unique_commits": unique_commits,
            "behind_commits": behind_commits,
        }
    if unique_commits == 0 and behind_commits > 0:
        git_run(["merge", f"origin/{parent_branch}"], repo_path)
        return {
            "action": "merged",
            "detail": f"merged origin/{parent_branch}",
            "behind_commits": behind_commits,
        }
    return {
        "action": "skipped",
        "detail": "already up to date with story branch",
        "unique_commits": unique_commits,
        "behind_commits": behind_commits,
    }


def _render_verify_summary(verify: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"ok": verify.get("ok")}
    tiers = verify.get("tiers") or {}
    if tiers:
        summary["tiers"] = {
            name: summarize_tier_result(entry if isinstance(entry, dict) else {})
            for name, entry in tiers.items()
        }
    return summary


def render_report(
    ctx: dict[str, Any],
    *,
    checkout: dict[str, Any] | None = None,
    commit: dict[str, Any] | None = None,
    pr: dict[str, Any] | None = None,
    verify: dict[str, Any] | None = None,
    gates: dict[str, Any] | None = None,
    status_start: dict[str, Any] | None = None,
    status_end: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checkout = checkout or {}
    commit = commit or {}
    pr_data = pr or {}
    verify = verify or {}
    gates = gates or {}
    status_start = status_start or {}
    status_end = status_end or {}

    branch_link = checkout.get("branch_issue_link") or pr_data.get("branch_issue_link") or {}
    task_link = pr_data.get("task_issue_link") or {}

    return {
        "task": {
            "url": ctx.get("task_issue", {}).get("url"),
            "status_start": status_start.get("status"),
            "status_end": status_end.get("status"),
        },
        "story": {
            "url": (ctx.get("story_issue") or {}).get("url"),
            "ac_ids": ctx.get("ac_ids") or [],
        },
        "branch": {
            "name": ctx.get("task_branch", {}).get("branch"),
            "linked": bool(branch_link.get("linked") or branch_link.get("already_linked")),
        },
        "commit": {
            "sha": commit.get("commit"),
            "message": commit.get("message"),
        },
        "pr": {
            "url": pr_data.get("url"),
            "task_linked": bool(task_link.get("linked")),
            "skipped": pr_data.get("skipped"),
            "reason": pr_data.get("reason"),
        },
        "verify": _render_verify_summary(verify),
        "gates": {"ok": gates.get("ok")},
        "build_hints": ctx.get("build_hints") or {},
        "tdd": {"agent_attested": None},
        "simplify": {"agent_attested": None},
    }


def find_work_issue_entry(
    manifest: dict[str, Any],
    task_repo: str,
    task_number: int,
) -> tuple[str | None, dict[str, Any] | None]:
    for task_id, entry in (manifest.get("work_issues") or {}).items():
        if entry.get("repo") == task_repo and int(entry.get("number", 0)) == task_number:
            return task_id, entry
    return None, None


def proposed_task_branch_name(
    story_id: str | None,
    task_title: str,
    task_id: str | None = None,
    task_number: int | None = None,
) -> str:
    if task_id:
        return task_branch_name(task_id, task_title)
    title = re.sub(r"^Task:\s*", "", task_title, flags=re.IGNORECASE).strip()
    if story_id is None:
        return f"bug/{task_number}-{slugify_story_title(title)}"
    return f"task/{story_id}-{slugify_story_title(title)}"


def resolve_task_branch(
    task_repo: str,
    task_number: int,
    body: str,
    manifest: dict[str, Any],
    task_title: str,
    story_id: str,
) -> dict[str, Any]:
    task_id, work_entry = find_work_issue_entry(manifest, task_repo, task_number)
    sources: list[str] = []

    linked = sorted(linked_branches(task_repo, task_number))
    task_linked = [b for b in linked if b.startswith("task/")]
    if task_linked:
        return {"branch": task_linked[0], "source": "linked", "linked": linked}
    if linked:
        return {"branch": linked[0], "source": "linked", "linked": linked}

    body_branch = parse_development_branch(body)
    if body_branch:
        return {"branch": body_branch, "source": "issue_body", "linked": linked}

    if work_entry and work_entry.get("branch"):
        return {
            "branch": work_entry["branch"],
            "source": "manifest",
            "linked": linked,
            "task_id": task_id,
        }

    proposed = proposed_task_branch_name(story_id, task_title, task_id, task_number)
    return {
        "branch": proposed,
        "source": "proposed",
        "linked": linked,
        "task_id": task_id,
    }


def resolve_story_issue_repo(
    task_repo: str,
    story_number: int,
    manifest: dict[str, Any],
    work_entry: dict[str, Any] | None,
    story_id: str,
) -> str:
    if work_entry:
        story_issue = work_entry.get("story_issue") or {}
        if story_issue.get("repo"):
            return story_issue["repo"]
    story_entry = (manifest.get("stories") or {}).get(story_id) or {}
    if story_entry.get("repo"):
        return story_entry["repo"]
    return task_repo


def resolve_parent_branch(
    task_repo: str,
    story_repo: str,
    story_number: int,
    story_id: str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    story_entry = (manifest.get("stories") or {}).get(story_id) or {}
    manifest_branch = story_entry.get("branch")
    if manifest_branch and remote_branch_exists(task_repo, manifest_branch):
        return {
            "branch": manifest_branch,
            "source": "manifest",
            "exists_on_remote": True,
        }

    try:
        story_body = gh_json(
            [
                "issue",
                "view",
                str(story_number),
                "--repo",
                story_repo,
                "--json",
                "body",
            ]
        ).get("body", "")
    except subprocess.CalledProcessError:
        story_body = ""

    for row in parse_development_branches_table(story_body):
        if row["repo"] == task_repo and remote_branch_exists(task_repo, row["branch"]):
            return {
                "branch": row["branch"],
                "source": "story_issue_table",
                "exists_on_remote": True,
            }

    linked = sorted(linked_branches(story_repo, story_number))
    for branch in linked:
        if branch.startswith("user-story/") and remote_branch_exists(task_repo, branch):
            return {
                "branch": branch,
                "source": "story_linked",
                "exists_on_remote": True,
            }

    if manifest_branch:
        return {
            "branch": manifest_branch,
            "source": "manifest",
            "exists_on_remote": False,
        }
    return {"branch": None, "source": "none", "exists_on_remote": False}


def extract_ac_scenarios(story_body: str, ac_ids: list[str]) -> dict[str, str]:
    if not ac_ids:
        return {}
    wanted = {aid.upper() for aid in ac_ids}
    scenarios: dict[str, str] = {}
    parts = AC_HEADING_PATTERN.split(story_body)
    if len(parts) < 2:
        return scenarios
    for index in range(1, len(parts), 2):
        ac_id = parts[index].upper()
        if ac_id not in wanted:
            continue
        content = parts[index + 1] if index + 1 < len(parts) else ""
        next_heading = re.search(r"^###\s+", content, re.MULTILINE)
        if next_heading:
            content = content[: next_heading.start()]
        scenarios[ac_id] = content.strip()
    return scenarios


def check_blockers(blockers: list[dict[str, str]]) -> dict[str, Any]:
    open_blockers: list[dict[str, Any]] = []
    for blocker in blockers:
        repo = blocker["repo"]
        number = int(blocker["number"])
        try:
            ref = issue_ref(repo, number)
        except subprocess.CalledProcessError as exc:
            open_blockers.append(
                {
                    "repo": repo,
                    "number": number,
                    "state": "UNKNOWN",
                    "error": str(exc),
                }
            )
            continue
        if ref.state == "OPEN":
            open_blockers.append(
                {
                    "repo": repo,
                    "number": number,
                    "state": ref.state,
                    "url": ref.url,
                }
            )
    return {
        "passed": not open_blockers,
        "open_blockers": open_blockers,
    }


def project_from_graphql_node(node: dict[str, Any]) -> dict[str, Any] | None:
    proj = node.get("project") or {}
    project_id = proj.get("id")
    number_val = proj.get("number")
    if not project_id or not number_val:
        return None
    owner_node = proj.get("owner") or {}
    owner = owner_node.get("login") or ""
    if not owner:
        return None
    return {
        "owner": owner,
        "number": int(number_val),
        "id": project_id,
        "title": proj.get("title"),
    }


def resolve_project_from_issue_graphql(
    task_repo: str,
    task_number: int,
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    owner, name = parse_repo(task_repo)
    try:
        data = graphql(
            ISSUE_PROJECT_ITEMS_QUERY,
            {"owner": owner, "name": name, "number": int(task_number)},
        )
    except subprocess.CalledProcessError:
        return None
    nodes = (
        data.get("data", {})
        .get("repository", {})
        .get("issue", {})
        .get("projectItems", {})
        .get("nodes", [])
    )
    if not nodes:
        return None

    manifest_project = (manifest or {}).get("project") or {}
    manifest_number = manifest_project.get("number")
    manifest_title = manifest_project.get("title")

    if manifest_number or manifest_title:
        for node in nodes:
            proj = node.get("project") or {}
            if manifest_number and int(proj.get("number") or 0) == int(manifest_number):
                return project_from_graphql_node(node)
            if manifest_title and proj.get("title") == manifest_title:
                return project_from_graphql_node(node)

    if len(nodes) == 1:
        return project_from_graphql_node(nodes[0])
    return None


def resolve_project_for_task(
    task_url: str,
    manifest: dict[str, Any],
    task_repo: str,
) -> dict[str, Any] | None:
    project = resolve_project_config(manifest, {}, default_owner=parse_repo(task_repo)[0])
    if project:
        return project

    repo, number = parse_issue_url(task_url) or (task_repo, 0)
    if number:
        project = resolve_project_from_issue_graphql(repo, int(number), manifest=manifest)
        if project:
            return project

    if not number:
        return None
    try:
        data = gh_json(
            [
                "issue",
                "view",
                str(number),
                "--repo",
                repo,
                "--json",
                "projectItems",
            ]
        )
    except subprocess.CalledProcessError:
        return None
    items = data.get("projectItems") or []
    if not items:
        return None

    item = items[0]
    proj = item.get("project") or {}
    owner = proj.get("owner", {}).get("login") or parse_repo(task_repo)[0]
    number_val = proj.get("number")
    project_id = proj.get("id")
    if number_val and project_id:
        return {
            "owner": owner,
            "number": int(number_val),
            "id": project_id,
            "title": proj.get("title"),
        }

    titles = {entry.get("title") for entry in items if entry.get("title")}
    if len(titles) == 1:
        return resolve_project_config(
            {"project": {"title": next(iter(titles))}},
            {},
            default_owner=owner,
        )
    return None


def get_status_field_options(
    owner: str,
    project_number: int,
) -> tuple[str | None, dict[str, str]]:
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
    status_field_id: str | None = None
    options: dict[str, str] = {}
    for field in data.get("fields", []):
        if field.get("name") != "Status":
            continue
        status_field_id = field.get("id")
        for option in field.get("options") or []:
            name = option.get("name") or ""
            option_id = option.get("id")
            if not option_id:
                continue
            for key, pattern in STATUS_PATTERNS.items():
                if pattern.match(name):
                    options[key] = option_id
    return status_field_id, options


def _status_key_from_raw(raw: str | None) -> str | None:
    if not raw:
        return None
    text = str(raw).strip()
    for key, pattern in STATUS_PATTERNS.items():
        if pattern.match(text):
            return key
    return None


def get_project_item_status_key(
    owner: str,
    project_number: int,
    issue_url: str,
) -> tuple[str | None, str | None]:
    """Return (item_id, status_key) for an issue on the project board."""
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
            if content.get("url") != issue_url:
                continue
            item_id = item.get("id")
            # gh project item-list exposes Status as a top-level field name.
            status_raw = item.get("Status") or item.get("status")
            if status_raw is None and isinstance(item.get("fields"), list):
                for field in item["fields"]:
                    if (field.get("name") or "") == "Status":
                        status_raw = field.get("value") or field.get("name")
                        break
            return item_id, _status_key_from_raw(
                status_raw if isinstance(status_raw, str) else None
            )
        page = data.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
    return None, None


def set_project_status(
    project: dict[str, Any],
    issue_url: str,
    status_key: str,
) -> dict[str, Any]:
    owner = project["owner"]
    number = int(project["number"])
    project_id = project["id"]
    item_id, current_key = get_project_item_status_key(owner, number, issue_url)
    if not item_id:
        # Fall back to find_project_item_id for boards that omit Status in list.
        item_id = find_project_item_id(owner, number, issue_url)
        current_key = None
    if not item_id:
        return {
            "ok": False,
            "warn": f"task issue not on project board: {issue_url}",
        }
    if current_key == status_key:
        return {
            "ok": True,
            "status": status_key,
            "item_id": item_id,
            "noop": True,
        }
    field_id, options = get_status_field_options(owner, number)
    if not field_id:
        return {"ok": False, "warn": "project has no Status field"}
    option_id = options.get(status_key)
    if not option_id:
        return {
            "ok": False,
            "warn": f"no Status option for {status_key!r}; available: {sorted(options)}",
        }
    try:
        graphql(
            UPDATE_PROJECT_STATUS_MUTATION,
            {
                "projectId": project_id,
                "itemId": item_id,
                "fieldId": field_id,
                "optionId": option_id,
            },
        )
    except subprocess.CalledProcessError as exc:
        return {
            "ok": False,
            "warn": f"project status update failed: {exc.stderr or exc}",
            "item_id": item_id,
        }
    return {"ok": True, "status": status_key, "item_id": item_id, "noop": False}


def upsert_development_branch(body: str, branch: str) -> str:
    block = f"## Development branch\n\n`{branch}`"
    if DEV_BRANCH_SECTION.search(body):
        return DEV_BRANCH_BACKTICK.sub(block, body, count=1)
    trace_end = section_text(body, "## Traceability")
    if trace_end:
        marker = "## Traceability"
        match = re.search(rf"^{re.escape(marker)}\s*$", body, re.IGNORECASE | re.MULTILINE)
        if match:
            insert_at = match.end()
            next_heading = re.search(r"^##\s+", body[insert_at:], re.MULTILINE)
            pos = insert_at + next_heading.start() if next_heading else len(body)
            return body[:pos].rstrip() + "\n\n" + block + "\n" + body[pos:].lstrip("\n")
    return body.rstrip() + "\n\n" + block + "\n"


def git_run(args: list[str], repo_path: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True,
        text=True,
        check=check,
    )


def resolve_worktree_path(worktree_root: str | None, main_repo_path: str, branch: str) -> str:
    """Sibling directory for a linked worktree, one per branch (slashes flattened)."""
    if worktree_root:
        base = Path(worktree_root)
    else:
        repo_dir = Path(main_repo_path).resolve()
        base = repo_dir.parent / f"{repo_dir.name}-worktrees"
    return str(base / branch.replace("/", "-"))


def git_worktree_add(
    main_repo_path: str,
    worktree_path: str,
    branch: str,
    *,
    base: str | None = None,
) -> None:
    """Create a linked worktree at worktree_path on branch, run from the main checkout.

    When base is given, branch is new: fetched from origin/base and created via
    `worktree add -b`. Otherwise branch already exists (locally or on origin) and is
    just checked out into the new worktree.
    """
    Path(worktree_path).parent.mkdir(parents=True, exist_ok=True)
    if base is not None:
        git_run(["fetch", "origin", base], main_repo_path)
        git_run(
            ["worktree", "add", "-b", branch, worktree_path, f"origin/{base}"],
            main_repo_path,
        )
    else:
        git_run(["fetch", "origin", branch], main_repo_path, check=False)
        git_run(["worktree", "add", worktree_path, branch], main_repo_path)


def git_worktree_remove(main_repo_path: str, worktree_path: str, *, force: bool = False) -> None:
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(worktree_path)
    git_run(args, main_repo_path)
    git_run(["worktree", "prune"], main_repo_path, check=False)


def build_context(
    task_repo: str,
    task_number: int,
    roots: list[Path],
) -> dict[str, Any]:
    data = gh_json(
        [
            "issue",
            "view",
            str(task_number),
            "--repo",
            task_repo,
            "--json",
            "number,title,body,state,url",
        ]
    )
    body = data.get("body") or ""
    parsed = parse_task_body(body)
    local_repo_path = find_local_repo_path(parsed["repository"], roots)
    manifest_path = find_manifest_path(parsed["spec_path"], local_repo_path)
    if not manifest_path:
        manifest_path = find_manifest_in_roots(roots)
        if manifest_path and not local_repo_path:
            toplevel = git_toplevel(manifest_path.parent)
            if toplevel:
                local_repo_path = str(toplevel)
    manifest = load_manifest(manifest_path) if manifest_path else {}

    task_id, work_entry = find_work_issue_entry(manifest, task_repo, task_number)

    standalone = parsed["story_number"] is None
    story_issue: dict[str, Any] | None
    if standalone:
        # No parent story — standalone issue (e.g. a bare bug report). Build
        # directly against the repo default branch instead of a story branch.
        story_issue = None
        ac_scenarios = {}
        parent_branch_info = {
            "branch": default_branch(parsed["repository"]),
            "source": "default_branch",
            "exists_on_remote": True,
        }
    else:
        story_repo = resolve_story_issue_repo(
            parsed["repository"],
            parsed["story_number"],
            manifest,
            work_entry,
            parsed["story_id"],
        )
        story_data = gh_json(
            [
                "issue",
                "view",
                str(parsed["story_number"]),
                "--repo",
                story_repo,
                "--json",
                "number,title,body,state,url",
            ]
        )
        ac_scenarios = extract_ac_scenarios(story_data.get("body") or "", parsed["ac_ids"])
        story_issue = {
            "repo": story_repo,
            "number": parsed["story_number"],
            "id": parsed["story_id"],
            "title": story_data.get("title"),
            "url": story_data.get("url"),
            "state": story_data.get("state"),
        }
        parent_branch_info = resolve_parent_branch(
            parsed["repository"],
            story_repo,
            parsed["story_number"],
            parsed["story_id"],
            manifest,
        )

    task_branch_info = resolve_task_branch(
        task_repo,
        task_number,
        body,
        manifest,
        data.get("title") or "",
        parsed["story_id"],
    )
    blocker_gate = check_blockers(parsed["blockers"])
    project = resolve_project_for_task(data["url"], manifest, task_repo)
    build_hints = infer_build_hints(
        task_summary=parsed["task_summary"],
        scope_files=parsed["scope_files"],
        title=data.get("title") or "",
    )

    return {
        "task_issue": {
            "repo": task_repo,
            "number": task_number,
            "title": data.get("title"),
            "url": data.get("url"),
            "state": data.get("state"),
        },
        "story_issue": story_issue,
        "repository": parsed["repository"],
        "local_repo_path": local_repo_path,
        "manifest_path": str(manifest_path) if manifest_path else None,
        "spec_path": parsed["spec_path"],
        "task_summary": parsed["task_summary"],
        "scope_files": parsed["scope_files"],
        "test_files": parsed["test_files"],
        "verify_cmd": parsed["verify_cmd"],
        "patterns": parsed["patterns"],
        "decisions": parsed.get("decisions") or [],
        "ac_ids": parsed["ac_ids"],
        "ac_scenarios": ac_scenarios,
        "blockers": parsed["blockers"],
        "blocker_gate": blocker_gate,
        "task_branch": task_branch_info,
        "parent_branch": parent_branch_info,
        "project": project,
        "work_issue_id": task_id,
        "build_hints": build_hints,
    }


def cmd_preflight(_args: argparse.Namespace) -> int:
    version_ok, version_detail = gh_version_ok()
    print(f"gh_version: {'ok' if version_ok else 'fail'} ({version_detail})")
    if not version_ok:
        return 1
    linked_ok = linked_branches_supported()
    print(f"linked_branches: {'supported' if linked_ok else 'unavailable'}")
    try:
        subprocess.run(["gh", "auth", "status"], check=True, capture_output=True)
        print("gh_auth: ok")
    except subprocess.CalledProcessError:
        print("gh_auth: missing or expired")
        return 1
    return 0


def run_start_phase(ctx: dict[str, Any], args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    strict = getattr(args, "strict", False)
    if not ctx["blocker_gate"]["passed"]:
        project = ensure_context_project(ctx, args)
        status_result: dict[str, Any] = {
            "ok": False,
            "skipped": True,
            "reason": "open blockers",
        }
        if project:
            status_result = set_project_status(project, ctx["task_issue"]["url"], "todo")
        ctx["status_update"] = status_result
        return ctx, 1
    project = ensure_context_project(ctx, args)
    status_result = {"ok": False, "skipped": True, "reason": "no project"}
    if project:
        status_result = set_project_status(project, ctx["task_issue"]["url"], "in_progress")
    ctx["status_update"] = status_result
    return ctx, start_exit_code(status_result, strict)


def run_checkout_phase(ctx: dict[str, Any], args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if not ctx["blocker_gate"]["passed"]:
        raise SystemExit(
            "blocker gate failed: "
            + json.dumps(ctx["blocker_gate"]["open_blockers"], indent=2)
        )

    repo_path = args.repo_path or ctx.get("local_repo_path")
    if not repo_path:
        raise SystemExit(
            f"no local checkout for {ctx['repository']}; pass --repo-path"
        )

    repo = ctx["task_issue"]["repo"]
    number = int(ctx["task_issue"]["number"])
    task_branch = ctx["task_branch"]["branch"]
    parent = ctx["parent_branch"]
    parent_branch = parent.get("branch")
    created = False
    source = ctx["task_branch"]["source"]

    main_repo_path = repo_path
    use_worktree = getattr(args, "worktree", False)
    worktree_path = (
        resolve_worktree_path(getattr(args, "worktree_root", None), main_repo_path, task_branch)
        if use_worktree
        else None
    )

    if source == "proposed":
        if not parent_branch or not parent.get("exists_on_remote"):
            base = resolve_task_branch_base(
                ctx["repository"],
                load_manifest(Path(ctx["manifest_path"])) if ctx.get("manifest_path") else {},
                ctx["story_issue"]["id"],
            )
        else:
            base = parent_branch
        if args.dry_run:
            ctx["checkout"] = {
                "repo_path": repo_path,
                "branch": task_branch,
                "action": "create",
                "base": base,
                "worktree_path": worktree_path,
                "dry_run": True,
            }
            return ctx, 0
        if worktree_path:
            git_worktree_add(main_repo_path, worktree_path, task_branch, base=base)
            repo_path = worktree_path
            git_run(["push", "-u", "origin", task_branch], repo_path)
        else:
            git_run(["fetch", "origin", base], repo_path)
            git_run(["checkout", "-b", task_branch, f"origin/{base}"], repo_path)
            git_run(["push", "-u", "origin", task_branch], repo_path)
        created = True
        issue_data = gh_json(
            [
                "issue",
                "view",
                str(number),
                "--repo",
                repo,
                "--json",
                "title,body",
            ]
        )
        new_body = upsert_development_branch(issue_data.get("body") or "", task_branch)
        edit_issue(repo, number, issue_data["title"], new_body)
        if ctx.get("manifest_path"):
            manifest = load_manifest(Path(ctx["manifest_path"]))
            task_id = ctx.get("work_issue_id")
            if task_id:
                work_issues = dict(manifest.get("work_issues") or {})
                entry = dict(work_issues.get(task_id) or {})
                entry["branch"] = task_branch
                work_issues[task_id] = entry
                manifest["work_issues"] = work_issues
                save_manifest(Path(ctx["manifest_path"]), manifest)
    else:
        if args.dry_run:
            ctx["checkout"] = {
                "repo_path": repo_path,
                "branch": task_branch,
                "action": "checkout",
                "worktree_path": worktree_path,
                "dry_run": True,
            }
            return ctx, 0
        if worktree_path:
            git_worktree_add(main_repo_path, worktree_path, task_branch)
            repo_path = worktree_path
        else:
            git_run(["fetch", "origin", task_branch], repo_path)
            result = git_run(["checkout", task_branch], repo_path, check=False)
            if result.returncode != 0:
                git_run(["checkout", "-b", task_branch, f"origin/{task_branch}"], repo_path)

    current = git_run(["branch", "--show-current"], repo_path).stdout.strip()
    if current != task_branch:
        raise SystemExit(f"expected branch {task_branch}, on {current}")

    branch_link = ensure_task_branch_linked(ctx)

    story_sync: dict[str, Any] = {"action": "skipped", "detail": "sync-story not requested"}
    if getattr(args, "sync_story", False) and not created:
        story_sync = sync_story_branch(
            repo_path,
            parent_branch=parent_branch,
            created=created,
        )

    ctx["checkout"] = {
        "repo_path": repo_path,
        "branch": task_branch,
        "current_branch": current,
        "created": created,
        "source": source,
        "branch_issue_link": branch_link,
        "story_sync": story_sync,
        "worktree_path": worktree_path,
        "main_repo_path": main_repo_path if worktree_path else None,
    }
    if worktree_path:
        ctx["local_repo_path"] = repo_path
        ctx["main_repo_path"] = main_repo_path
    if args.dry_run:
        ctx["test_harness"] = {"bootstrapped": False, "created": [], "skipped": True, "reason": "dry-run"}
    else:
        ctx["test_harness"] = ensure_test_harness(repo_path)
    return ctx, 0


def cmd_context(args: argparse.Namespace) -> int:
    repo, number = parse_issue_spec(args.issue, default_repo=args.repo)
    ctx = build_context(repo, number, workspace_roots_from_args(args))
    write_json(args.output, ctx)
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    repo, number = parse_issue_spec(args.issue, default_repo=args.repo)
    ctx = build_context(repo, number, workspace_roots_from_args(args))
    ctx, code = run_start_phase(ctx, args)
    write_json(args.output, ctx)
    return code


def cmd_checkout(args: argparse.Namespace) -> int:
    repo, number = parse_issue_spec(args.issue, default_repo=args.repo)
    ctx = build_context(repo, number, workspace_roots_from_args(args))
    ctx, code = run_checkout_phase(ctx, args)
    write_json(args.output, ctx)
    return code


def cmd_cleanup_worktree(args: argparse.Namespace) -> int:
    ctx: dict[str, Any] = load_json(args.input) if args.input else {}
    checkout = ctx.get("checkout") or {}
    repo_path = args.repo_path or ctx.get("main_repo_path") or checkout.get("main_repo_path")
    worktree_path = args.worktree_path or checkout.get("worktree_path")
    if not repo_path or not worktree_path:
        raise SystemExit(
            "cleanup-worktree needs --repo-path (main repo) and --worktree-path, "
            "or --input pointing at a checkout.json/context.json produced with --worktree"
        )

    git_worktree_remove(repo_path, worktree_path, force=args.force)
    result: dict[str, Any] = {
        "repo_path": repo_path,
        "worktree_path": worktree_path,
        "removed": True,
        "branch_deleted": None,
    }

    if args.delete_branch:
        branch = (
            args.branch
            or ctx.get("task_branch", {}).get("branch")
            or checkout.get("branch")
        )
        if not branch:
            raise SystemExit(
                "--delete-branch needs --branch, or --input with task_branch/checkout.branch"
            )
        git_run(["branch", "-D" if args.force else "-d", branch], repo_path)
        result["branch_deleted"] = branch

    write_json(args.output, result)
    print(json.dumps(result, indent=2))
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    repo, number = parse_issue_spec(args.issue, default_repo=args.repo)
    ctx = build_context(repo, number, workspace_roots_from_args(args))

    ctx, start_code = run_start_phase(ctx, args)
    state_dir = getattr(args, "state_dir", None)
    if state_dir:
        sd = Path(state_dir)
        write_json(state_file_path(sd, "context"), ctx)
    elif args.output:
        write_json(args.output, ctx)
    if start_code != 0:
        return start_code

    ctx, checkout_code = run_checkout_phase(ctx, args)
    if state_dir:
        sd = Path(state_dir)
        write_json(state_file_path(sd, "context"), ctx)
        write_json(state_file_path(sd, "checkout"), ctx)
    elif args.output:
        write_json(args.output, ctx)
    return checkout_code


def ensure_context_project(
    ctx: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any] | None:
    project = ctx.get("project")
    if project:
        return project
    repo = ctx["task_issue"]["repo"]
    number = int(ctx["task_issue"]["number"])
    fresh = build_context(repo, number, workspace_roots_from_args(args))
    return fresh.get("project")


def cmd_set_status(args: argparse.Namespace) -> int:
    status_key = args.status.replace("-", "_")
    if status_key not in STATUS_PATTERNS:
        raise SystemExit(f"unknown status {args.status!r}")
    repo, number = parse_issue_spec(args.issue, default_repo=args.repo)
    ctx = build_context(repo, number, workspace_roots_from_args(args))
    project = ensure_context_project(ctx, args)
    if not project:
        raise SystemExit("could not resolve GitHub project for task issue")
    result = set_project_status(project, ctx["task_issue"]["url"], status_key)
    write_json(args.output, {"status_update": result, "task_issue": ctx["task_issue"], "project": project})
    return 0 if result.get("ok") else 1


def open_pr_for_context(ctx: dict[str, Any]) -> dict[str, Any]:
    task_repo = ctx["repository"]
    task_branch = ctx["task_branch"]["branch"]
    branch_link = ensure_task_branch_linked(ctx)
    parent = ctx["parent_branch"]
    parent_branch = parent.get("branch")
    if not parent_branch:
        return {
            "ok": False,
            "skipped": True,
            "reason": "no parent issue branch resolved",
            "branch_issue_link": branch_link,
        }
    if not parent.get("exists_on_remote"):
        return {
            "ok": False,
            "skipped": True,
            "reason": f"parent branch {parent_branch!r} not on remote",
            "parent_branch": parent_branch,
            "branch_issue_link": branch_link,
        }

    existing = gh_json(
        [
            "pr",
            "list",
            "--repo",
            task_repo,
            "--head",
            task_branch,
            "--base",
            parent_branch,
            "--state",
            "open",
            "--json",
            "number,url,title",
        ]
    )
    task_number = int(ctx["task_issue"]["number"])
    link_keyword = task_issue_link_keyword(task_repo, task_number)

    if existing:
        pr = existing[0]
        pr_number = int(pr["number"])
        link_result = ensure_pr_links_task_issue(task_repo, pr_number, task_number)
        return {
            "ok": True,
            "action": "existing",
            "number": pr_number,
            "url": pr.get("url"),
            "head": task_branch,
            "base": parent_branch,
            "branch_issue_link": branch_link,
            "task_issue_link": link_result,
            "link_keyword": link_keyword,
        }

    story = ctx["story_issue"]
    task = ctx["task_issue"]
    body = render_pr_body(ctx)
    raw_title = task.get("title") or ""
    short_title = re.sub(r"^Task:\s*", "", raw_title, flags=re.I)
    title = f"Task: {short_title} ({story['id']})" if story else f"Bug: {short_title}"
    pr_url = gh_run(
        [
            "pr",
            "create",
            "--repo",
            task_repo,
            "--head",
            task_branch,
            "--base",
            parent_branch,
            "--title",
            title,
            "--body",
            body,
        ]
    ).strip()
    return {
        "ok": True,
        "action": "created",
        "url": pr_url,
        "head": task_branch,
        "base": parent_branch,
        "branch_issue_link": branch_link,
        "task_issue_link": {
            "linked": True,
            "action": "created_with_body",
            "link_keyword": link_keyword,
        },
        "link_keyword": link_keyword,
    }


def cmd_open_pr(args: argparse.Namespace) -> int:
    ctx = load_json(args.input) if args.input else build_context(
        *parse_issue_spec(args.issue, default_repo=args.repo),
        workspace_roots_from_args(args),
    )
    result = open_pr_for_context(ctx)
    write_json(args.output, {"pr": result, "task_issue": ctx["task_issue"]})
    return 0 if result.get("ok") or result.get("skipped") else 1


def cmd_finish(args: argparse.Namespace) -> int:
    ctx = load_json(args.input) if args.input else build_context(
        *parse_issue_spec(args.issue, default_repo=args.repo),
        workspace_roots_from_args(args),
    )
    strict = getattr(args, "strict", True)
    pr_result = open_pr_for_context(ctx)
    status_result: dict[str, Any] = {"ok": False, "skipped": True, "reason": "no project"}
    project = ensure_context_project(ctx, args)
    if project:
        status_result = set_project_status(
            project, ctx["task_issue"]["url"], "review_qa"
        )
    summary = {
        "task_issue": ctx["task_issue"],
        "story_issue": ctx["story_issue"],
        "task_branch": ctx["task_branch"],
        "parent_branch": ctx["parent_branch"],
        "pr": pr_result,
        "status_update": status_result,
    }
    write_json(args.output, summary)
    return finish_exit_code(pr_result, status_result, strict)


def render_commit_message(ctx: dict[str, Any]) -> str:
    story = ctx["story_issue"]
    task = ctx["task_issue"]
    ac_list = ", ".join(ctx.get("ac_ids") or [])
    summary = (ctx.get("task_summary") or "implement task").splitlines()[0].strip()
    scope_hint = Path(ctx["scope_files"][0]).stem if ctx.get("scope_files") else "task"
    trailer = (
        f"{story['id']}, {ac_list}, {task['repo']}#{task['number']}"
        if story
        else f"{task['repo']}#{task['number']}"
    )
    return f"feat({scope_hint}): {summary} ({trailer})"


def cmd_commit_push(args: argparse.Namespace) -> int:
    ctx = load_json(args.input) if args.input else build_context(
        *parse_issue_spec(args.issue, default_repo=args.repo),
        workspace_roots_from_args(args),
    )
    repo_path = args.repo_path or ctx.get("local_repo_path")
    if not repo_path:
        raise SystemExit("no local repo path; pass --repo-path")
    strict = getattr(args, "strict", True)
    allow_out_of_scope = getattr(args, "allow_out_of_scope", False)
    files = collect_commit_files(ctx, repo_path)
    message = args.message or render_commit_message(ctx)
    if args.dry_run:
        write_json(
            args.output,
            {
                "dry_run": True,
                "repo_path": repo_path,
                "files": files,
                "message": message,
                "branch": ctx["task_branch"]["branch"],
            },
        )
        return 0

    verify_result = None
    if getattr(args, "verify_result", None):
        verify_result = load_json(args.verify_result)
    if strict:
        gates_result = run_gates(
            ctx,
            repo_path,
            require_verify=True,
            verify_result=verify_result,
            allow_out_of_scope=allow_out_of_scope,
        )
        if not gates_result["ok"]:
            write_json(args.output, {"gates": gates_result, "commit": None})
            return 1

    if files:
        git_run(["add", *files], repo_path)
    staged = git_run(["diff", "--cached", "--name-only"], repo_path, check=False).stdout.strip()
    if not staged:
        raise SystemExit("nothing to commit after staging scope/test files")

    git_run(["commit", "-m", message], repo_path)
    git_run(["push", "-u", "origin", "HEAD"], repo_path)
    sha = git_run(["rev-parse", "HEAD"], repo_path).stdout.strip()
    result = {
        "repo_path": repo_path,
        "branch": ctx["task_branch"]["branch"],
        "commit": sha,
        "message": message,
        "files": files,
    }
    write_json(args.output, result)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    ctx = load_json(args.input) if args.input else build_context(
        *parse_issue_spec(args.issue, default_repo=args.repo),
        workspace_roots_from_args(args),
    )
    repo_path = args.repo_path or ctx.get("local_repo_path")
    if not repo_path:
        raise SystemExit("no local repo path; pass --repo-path")
    result = run_verify(ctx, repo_path)
    write_json(args.output, result)
    return 0 if result.get("ok") else 1


def cmd_bootstrap_harness(args: argparse.Namespace) -> int:
    repo_path = args.repo_path
    if not repo_path:
        raise SystemExit("bootstrap-harness requires --repo-path")
    result = ensure_test_harness(repo_path)
    write_json(args.output, result)
    return 0


def cmd_gates(args: argparse.Namespace) -> int:
    ctx = load_json(args.input) if args.input else build_context(
        *parse_issue_spec(args.issue, default_repo=args.repo),
        workspace_roots_from_args(args),
    )
    repo_path = args.repo_path or ctx.get("local_repo_path")
    if not repo_path:
        raise SystemExit("no local repo path; pass --repo-path")
    verify_result = load_json(args.verify_result) if getattr(args, "verify_result", None) else None
    result = run_gates(
        ctx,
        repo_path,
        require_verify=getattr(args, "require_verify", False),
        verify_result=verify_result,
        allow_out_of_scope=getattr(args, "allow_out_of_scope", False),
    )
    write_json(args.output, result)
    return 0 if result.get("ok") else 1


def cmd_report(args: argparse.Namespace) -> int:
    ctx = load_json(args.input) if args.input else build_context(
        *parse_issue_spec(args.issue, default_repo=args.repo),
        workspace_roots_from_args(args),
    )
    checkout_data = load_json(args.checkout) if getattr(args, "checkout", None) else {}
    commit = load_json(args.commit) if getattr(args, "commit", None) else {}
    verify = load_json(args.verify_json) if getattr(args, "verify_json", None) else {}
    gates = load_json(args.gates_json) if getattr(args, "gates_json", None) else {}

    pr_payload: dict[str, Any] = {}
    if getattr(args, "pr", None):
        loaded = load_json(args.pr)
        pr_payload = loaded.get("pr", loaded)

    finish_payload = load_json(args.finish) if getattr(args, "finish", None) else {}
    status_start = (
        ctx.get("status_update")
        or checkout_data.get("status_update")
        or {}
    )
    status_end = finish_payload.get("status_update", {}) if finish_payload else {}
    checkout_section = checkout_data.get("checkout", checkout_data) if checkout_data else None

    report = render_report(
        ctx,
        checkout=checkout_section,
        commit=commit,
        pr=pr_payload,
        verify=verify,
        gates=gates,
        status_start=status_start,
        status_end=status_end,
    )
    write_json(args.output, report)
    return 0


def cmd_finalize(args: argparse.Namespace) -> int:
    if not getattr(args, "ac_attested", False):
        raise SystemExit(
            "finalize requires --ac-attested (confirm all cited AC-* scenarios are satisfied)"
        )
    if not args.input:
        raise SystemExit("finalize requires --input or --state-dir")

    state_dir = Path(args.state_dir) if getattr(args, "state_dir", None) else None

    def step_output(key: str) -> str | None:
        if state_dir:
            return state_file_path(state_dir, key)
        return None

    gates_args = argparse.Namespace(**vars(args))
    gates_args.require_verify = True
    if not getattr(gates_args, "verify_result", None):
        verify_path = step_output("verify")
        if not verify_path or not Path(verify_path).exists():
            raise SystemExit("finalize requires --verify-result or verify.json in --state-dir")
        gates_args.verify_result = verify_path
    gates_args.output = step_output("gates") or args.output
    rc = cmd_gates(gates_args)
    if rc != 0:
        return rc

    commit_args = argparse.Namespace(**vars(args))
    commit_args.verify_result = gates_args.verify_result
    commit_args.output = step_output("commit")
    rc = cmd_commit_push(commit_args)
    if rc != 0:
        return rc

    finish_args = argparse.Namespace(**vars(args))
    finish_args.output = step_output("finish")
    rc = cmd_finish(finish_args)
    if rc != 0:
        return rc

    report_args = argparse.Namespace(**vars(args))
    report_args.checkout = (
        step_output("checkout")
        or args.input
    )
    report_args.verify_json = gates_args.verify_result
    report_args.gates_json = gates_args.output
    report_args.commit = commit_args.output
    report_args.finish = finish_args.output
    report_args.output = step_output("report") or args.output
    return cmd_report(report_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("preflight", help="Check gh auth and linked-branch support")

    def add_issue_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--issue", help="URL or OWNER/REPO#N")
        p.add_argument("--repo", help="Default repo when --issue is a number")
        p.add_argument("--input", help="Context JSON from context/start/prepare")
        p.add_argument("--output", "-o", help="Write JSON result to path")
        p.add_argument(
            "--workspace-root",
            action="append",
            help="Workspace root for local repo discovery (repeatable)",
        )
        add_state_dir_arg(p)

    def add_strict_args(p: argparse.ArgumentParser, *, default: bool) -> None:
        p.add_argument(
            "--strict",
            action="store_true",
            default=default,
            help="Fail with non-zero exit when status/gates/pr checks fail",
        )
        p.add_argument(
            "--no-strict",
            action="store_false",
            dest="strict",
            help="Warn-only mode for status/gates/pr checks",
        )

    ctx = sub.add_parser("context", help="Parse task issue and resolve branches (read-only)")
    add_issue_args(ctx)
    ctx.add_argument("--repo-path", help="Local git checkout path (for manifest/project discovery)")
    ctx.set_defaults(issue_required=True)

    prepare = sub.add_parser(
        "prepare",
        help="context + start (In-progress) + checkout (--sync-story optional)",
    )
    add_issue_args(prepare)
    prepare.add_argument("--repo-path", help="Local git checkout path")
    prepare.add_argument("--dry-run", action="store_true")
    prepare.add_argument(
        "--sync-story",
        action="store_true",
        help="Merge parent story branch when task branch has no unique commits and is behind",
    )
    prepare.add_argument(
        "--worktree",
        action="store_true",
        help="Check out the task branch into a new linked git worktree, not --repo-path in place",
    )
    prepare.add_argument(
        "--worktree-root",
        help="Directory to create the worktree under (default: sibling '<repo>-worktrees/' dir)",
    )
    add_strict_args(prepare, default=False)

    start = sub.add_parser("start", help="context + set Status In-progress")
    add_issue_args(start)
    start.add_argument("--repo-path", help="Local git checkout path (for manifest/project discovery)")
    add_strict_args(start, default=False)

    checkout = sub.add_parser("checkout", help="Resolve/create task branch and git checkout")
    add_issue_args(checkout)
    checkout.add_argument("--repo-path", help="Local git checkout path")
    checkout.add_argument("--dry-run", action="store_true")
    checkout.add_argument(
        "--sync-story",
        action="store_true",
        help="Merge parent story branch when task branch has no unique commits and is behind",
    )
    checkout.add_argument(
        "--worktree",
        action="store_true",
        help="Check out the task branch into a new linked git worktree, not --repo-path in place",
    )
    checkout.add_argument(
        "--worktree-root",
        help="Directory to create the worktree under (default: sibling '<repo>-worktrees/' dir)",
    )

    cleanup_worktree = sub.add_parser(
        "cleanup-worktree",
        help="Remove a linked worktree created by prepare/checkout --worktree",
    )
    cleanup_worktree.add_argument(
        "--input", help="checkout.json/context.json with worktree_path + main_repo_path"
    )
    cleanup_worktree.add_argument(
        "--repo-path", help="Main repo path (git worktree remove runs from here)"
    )
    cleanup_worktree.add_argument("--worktree-path", help="Worktree directory to remove")
    cleanup_worktree.add_argument(
        "--force", action="store_true", help="Force-remove even with uncommitted changes"
    )
    cleanup_worktree.add_argument(
        "--delete-branch",
        action="store_true",
        help="Also delete the task branch (local + remote) after removing the worktree",
    )
    cleanup_worktree.add_argument(
        "--branch", help="Branch name for --delete-branch (default: from --input)"
    )
    cleanup_worktree.add_argument("--output", "-o", help="Write JSON result to path")

    status = sub.add_parser("set-status", help="Set project Status on task issue")
    add_issue_args(status)
    status.add_argument("--repo-path", help="Local git checkout path (for manifest/project discovery)")
    status.add_argument(
        "--status",
        required=True,
        choices=["in-progress", "review-qa", "todo", "ready-to-ship"],
    )
    add_strict_args(status, default=True)

    open_pr = sub.add_parser("open-pr", help="Open or find PR task branch → parent branch")
    add_issue_args(open_pr)

    finish = sub.add_parser("finish", help="open-pr + set Status Review / QA")
    add_issue_args(finish)
    finish.add_argument("--repo-path", help="Local git checkout path (for manifest/project discovery)")
    add_strict_args(finish, default=True)

    commit = sub.add_parser("commit-push", help="Commit scope/test files and push task branch")
    add_issue_args(commit)
    commit.add_argument("--repo-path", help="Local git checkout path")
    commit.add_argument("--message", help="Commit message (default from context)")
    commit.add_argument("--dry-run", action="store_true")
    commit.add_argument(
        "--allow-out-of-scope",
        action="store_true",
        help="Allow changed files outside scope/test lists during gates check",
    )
    commit.add_argument(
        "--verify-result",
        help="Prior verify JSON output (skip re-running verify during gates)",
    )
    add_strict_args(commit, default=True)

    verify = sub.add_parser("verify", help="Run tier 1–4 scripts, task verify command, and legacy suite/build fallback")
    add_issue_args(verify)
    verify.add_argument("--repo-path", help="Local git checkout path")

    bootstrap = sub.add_parser(
        "bootstrap-harness",
        help="Copy tier test scripts and optional pytest smoke scaffold into a repo",
    )
    bootstrap.add_argument("--repo-path", required=True, help="Local git checkout path")
    bootstrap.add_argument("--output", "-o", help="Write JSON result to path")

    gates = sub.add_parser("gates", help="Pre-commit mechanical checks (branch, scope, blockers)")
    add_issue_args(gates)
    gates.add_argument("--repo-path", help="Local git checkout path")
    gates.add_argument(
        "--require-verify",
        action="store_true",
        help="Include verify step in gate checks",
    )
    gates.add_argument(
        "--verify-result",
        help="Prior verify JSON output instead of re-running verify",
    )
    gates.add_argument(
        "--allow-out-of-scope",
        action="store_true",
        help="Skip scope discipline failure for out-of-scope paths",
    )
    add_strict_args(gates, default=True)

    finalize = sub.add_parser(
        "finalize",
        help="After AC gate: gates + commit-push + finish + report",
    )
    add_issue_args(finalize)
    finalize.add_argument("--repo-path", help="Local git checkout path")
    finalize.add_argument(
        "--verify-result",
        help="Prior verify JSON output (default: verify.json in --state-dir)",
    )
    finalize.add_argument(
        "--allow-out-of-scope",
        action="store_true",
        help="Allow changed files outside scope/test lists during gates check",
    )
    finalize.add_argument(
        "--ac-attested",
        action="store_true",
        help="Required: agent confirms all cited AC-* scenarios are satisfied",
    )
    finalize.add_argument("--message", help="Commit message (default from context)")
    add_strict_args(finalize, default=True)

    report = sub.add_parser("report", help="Assemble gh-build present-output summary JSON")
    add_issue_args(report)
    report.add_argument("--checkout", help="Checkout step JSON path")
    report.add_argument("--commit", help="Commit-push step JSON path")
    report.add_argument("--pr", help="Open-pr or finish step JSON path")
    report.add_argument("--verify", dest="verify_json", help="Verify step JSON path")
    report.add_argument("--gates", dest="gates_json", help="Gates step JSON path")
    report.add_argument("--finish", help="Finish step JSON path (for end status)")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    apply_state_dir_defaults(args)
    needs_issue = args.command in {
        "context",
        "prepare",
        "start",
        "checkout",
        "set-status",
        "open-pr",
        "finish",
        "commit-push",
        "verify",
        "gates",
        "report",
    }
    if needs_issue and not args.issue and not getattr(args, "input", None):
        parser.error(f"{args.command} requires --issue or --input")

    if args.command == "preflight":
        return cmd_preflight(args)
    if args.command == "context":
        return cmd_context(args)
    if args.command == "prepare":
        return cmd_prepare(args)
    if args.command == "start":
        return cmd_start(args)
    if args.command == "checkout":
        return cmd_checkout(args)
    if args.command == "cleanup-worktree":
        return cmd_cleanup_worktree(args)
    if args.command == "set-status":
        return cmd_set_status(args)
    if args.command == "open-pr":
        return cmd_open_pr(args)
    if args.command == "finish":
        return cmd_finish(args)
    if args.command == "commit-push":
        return cmd_commit_push(args)
    if args.command == "verify":
        return cmd_verify(args)
    if args.command == "bootstrap-harness":
        return cmd_bootstrap_harness(args)
    if args.command == "gates":
        return cmd_gates(args)
    if args.command == "finalize":
        return cmd_finalize(args)
    if args.command == "report":
        return cmd_report(args)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
