"""Deterministic probes for Phase 4 maintenance jobs.

Each ``probe_*`` returns a dict:

    {
      "action": "noop" | "spawn" | "setup_alert",
      "inputs": {...},          # fingerprint inputs (canonical)
      "context": {...},         # prompt / logging extras
      "reason": str,
      "duplicate": bool,        # True when an open PR/issue already covers this
    }

Command and GitHub callers are injectable for tests.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Marker strings embedded in PR bodies / issue comments for GitHub-side dedupe.
MARKER_DEPS = "auto-workflow:maintenance:deps_bump"
MARKER_RUFF = "auto-workflow:maintenance:ruff_rules"
MARKER_DOCS = "auto-workflow:maintenance:docs_drift"
MARKER_STALE = "auto-workflow:maintenance:stale_triage"
MARKER_TIER7_SETUP = "auto-workflow:maintenance:tier7_setup"
MARKER_TIER7_ANOMALY = "auto-workflow:maintenance:tier7_anomaly"

RUFF_CANDIDATE_RULES = ("B", "SIM", "RUF", "PERF", "S")
PINNED_CDK_FILES = (
    ".github/workflows/ci.yml",
    ".github/workflows/deploy.yml",
    "docs/DEPLOYMENT.md",
    "AGENTS.md",
)
REQ_FILES = (
    "requirements-cdk.txt",
    "requirements-dev.txt",
    "requirements-test.txt",
)


def _run_cmd(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    run_fn: Callable[..., subprocess.CompletedProcess] | None = None,
) -> subprocess.CompletedProcess:
    run_fn = run_fn or subprocess.run
    return run_fn(
        args,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def parse_requirement_floors(text: str) -> dict[str, str]:
    """Parse ``pkg>=X`` floors from a requirements file body."""
    floors: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-r "):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)\s*>=\s*([^,<\s]+)", line)
        if match:
            floors[match.group(1).lower()] = match.group(2)
    return floors


def parse_cdk_cli_pin(text: str) -> str | None:
    match = re.search(r'CDK_CLI_VERSION:\s*"([^"]+)"', text)
    if match:
        return match.group(1)
    match = re.search(r"aws-cdk@([0-9]+\.[0-9]+\.[0-9]+)", text)
    if match:
        return match.group(1)
    match = re.search(r"pinned to `([0-9]+\.[0-9]+\.[0-9]+)`", text)
    if match:
        return match.group(1)
    return None


def read_current_pins(repo_root: Path) -> dict[str, Any]:
    floors: dict[str, str] = {}
    for rel in REQ_FILES:
        path = repo_root / rel
        if path.is_file():
            floors.update(parse_requirement_floors(path.read_text()))
    cdk_cli = None
    for rel in PINNED_CDK_FILES:
        path = repo_root / rel
        if path.is_file():
            found = parse_cdk_cli_pin(path.read_text())
            if found:
                cdk_cli = found
                break
    return {"floors": floors, "cdk_cli": cdk_cli}


def discover_latest_versions(
    packages: list[str],
    *,
    run_fn: Callable[..., subprocess.CompletedProcess] | None = None,
    npm_package: str = "aws-cdk",
) -> dict[str, str]:
    """Best-effort latest versions via ``pip index`` / ``npm view``."""
    latest: dict[str, str] = {}
    for pkg in packages:
        result = _run_cmd(
            ["python3", "-m", "pip", "index", "versions", pkg],
            run_fn=run_fn,
        )
        if result.returncode != 0:
            continue
        # First line: "pkg (x.y.z)"
        match = re.search(r"\(([0-9][^)]*)\)", result.stdout.splitlines()[0] if result.stdout else "")
        if match:
            latest[pkg.lower()] = match.group(1).split(",")[0].strip()
    npm = _run_cmd(["npm", "view", npm_package, "version"], run_fn=run_fn)
    if npm.returncode == 0 and npm.stdout.strip():
        latest["aws-cdk"] = npm.stdout.strip()
    return latest


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = re.split(r"[^\d]+", version)
    nums = []
    for part in parts:
        if part.isdigit():
            nums.append(int(part))
    return tuple(nums) if nums else (0,)


def versions_need_bump(current: dict[str, Any], latest: dict[str, str]) -> dict[str, dict[str, str]]:
    bumps: dict[str, dict[str, str]] = {}
    for name, floor in (current.get("floors") or {}).items():
        cand = latest.get(name)
        if cand and _version_tuple(cand) > _version_tuple(floor):
            bumps[name] = {"from": floor, "to": cand}
    cdk = current.get("cdk_cli")
    npm_latest = latest.get("aws-cdk")
    if cdk and npm_latest and _version_tuple(npm_latest) > _version_tuple(cdk):
        bumps["aws-cdk"] = {"from": cdk, "to": npm_latest}
    return bumps


def _default_gh(*args: str) -> str:
    result = subprocess.run(
        ["gh", *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return "[]"
    return result.stdout


def find_open_prs_with_marker(
    repo: str,
    marker: str,
    *,
    gh_fn: Callable[..., str] | None = None,
) -> list[dict[str, Any]]:
    """Return open PRs whose body contains ``marker``."""
    gh = gh_fn or _default_gh
    raw = gh(
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--json",
        "number,url,title,body,headRefName",
        "--limit",
        "50",
    )
    try:
        prs = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [pr for pr in prs if marker in (pr.get("body") or "")]


def find_open_issues_with_marker(
    repo: str,
    marker: str,
    *,
    gh_fn: Callable[..., str] | None = None,
) -> list[dict[str, Any]]:
    """Return open issues whose body contains ``marker``."""
    gh = gh_fn or _default_gh
    raw = gh(
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--json",
        "number,url,title,body",
        "--limit",
        "50",
    )
    try:
        issues = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [issue for issue in issues if marker in (issue.get("body") or "")]


def probe_deps_bump(
    *,
    repo_root: Path,
    repo: str,
    run_fn: Callable[..., subprocess.CompletedProcess] | None = None,
    gh_fn: Callable[..., str] | None = None,
    latest_fn: Callable[..., dict[str, str]] | None = None,
) -> dict[str, Any]:
    current = read_current_pins(repo_root)
    packages = sorted(current.get("floors") or {})
    if latest_fn is not None:
        latest = latest_fn(packages)
    else:
        latest = discover_latest_versions(packages, run_fn=run_fn)
    bumps = versions_need_bump(current, latest)
    inputs = {"current": current, "bumps": bumps}
    if not bumps:
        return {
            "action": "noop",
            "inputs": inputs,
            "context": {"latest": latest},
            "reason": "no dependency bumps available",
            "duplicate": False,
        }
    open_prs = find_open_prs_with_marker(repo, MARKER_DEPS, gh_fn=gh_fn)
    if open_prs:
        return {
            "action": "noop",
            "inputs": inputs,
            "context": {"open_prs": open_prs, "latest": latest},
            "reason": "open deps_bump PR already exists",
            "duplicate": True,
        }
    return {
        "action": "spawn",
        "inputs": inputs,
        "context": {"bumps": bumps, "marker": MARKER_DEPS, "latest": latest},
        "reason": f"{len(bumps)} package(s) can be bumped",
        "duplicate": False,
    }


def probe_ruff_rules(
    *,
    repo_root: Path,
    repo: str,
    run_fn: Callable[..., subprocess.CompletedProcess] | None = None,
    gh_fn: Callable[..., str] | None = None,
    candidate_rules: tuple[str, ...] = RUFF_CANDIDATE_RULES,
) -> dict[str, Any]:
    pyproject = repo_root / "pyproject.toml"
    selected: list[str] = []
    if pyproject.is_file():
        text = pyproject.read_text()
        match = re.search(r"select\s*=\s*\[([^\]]+)\]", text)
        if match:
            selected = re.findall(r'"([A-Z0-9]+)"', match.group(1))
    opportunities: list[dict[str, Any]] = []
    paths = ["app.py", "infrastructure", "scripts", "tests", ".github/scripts"]
    for rule in candidate_rules:
        if rule in selected:
            continue
        result = _run_cmd(
            ["ruff", "check", *paths, "--select", rule, "--statistics"],
            cwd=repo_root,
            run_fn=run_fn,
        )
        # exit 0 = clean; we also accept auto-fixable noise as opportunity
        stdout = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0 and not stdout.strip():
            opportunities.append({"rule": rule, "clean": True, "fixable": False})
        elif "fixable" in stdout.lower() or result.returncode == 1:
            # Any findings count as an adoption opportunity for the agent to judge.
            opportunities.append(
                {
                    "rule": rule,
                    "clean": result.returncode == 0,
                    "fixable": "fixable" in stdout.lower(),
                    "sample": stdout[:500],
                }
            )
    inputs = {"selected": selected, "opportunities": [o["rule"] for o in opportunities]}
    if not opportunities:
        return {
            "action": "noop",
            "inputs": inputs,
            "context": {},
            "reason": "no ruff rule opportunities",
            "duplicate": False,
        }
    open_prs = find_open_prs_with_marker(repo, MARKER_RUFF, gh_fn=gh_fn)
    if open_prs:
        return {
            "action": "noop",
            "inputs": inputs,
            "context": {"open_prs": open_prs, "opportunities": opportunities},
            "reason": "open ruff_rules PR already exists",
            "duplicate": True,
        }
    return {
        "action": "spawn",
        "inputs": inputs,
        "context": {"opportunities": opportunities, "marker": MARKER_RUFF},
        "reason": f"{len(opportunities)} ruff rule opportunity(ies)",
        "duplicate": False,
    }


def agents_contract_hash(repo_root: Path) -> str:
    """Stable hash of AGENTS.md + CLAUDE.md for drift detection."""
    from hashlib import sha256

    h = sha256()
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = repo_root / name
        if path.is_file():
            h.update(name.encode())
            h.update(b"\0")
            h.update(path.read_bytes())
            h.update(b"\0")
    return h.hexdigest()[:32]


def probe_docs_drift(
    *,
    repo_root: Path,
    repo: str,
    checkpoint_hash: str | None,
    gh_fn: Callable[..., str] | None = None,
) -> dict[str, Any]:
    current = agents_contract_hash(repo_root)
    inputs = {"agents_hash": current, "checkpoint_hash": checkpoint_hash}
    if checkpoint_hash and checkpoint_hash == current:
        return {
            "action": "noop",
            "inputs": inputs,
            "context": {},
            "reason": "AGENTS/CLAUDE match last known-good checkpoint",
            "duplicate": False,
        }
    if checkpoint_hash is None:
        # First run: establish checkpoint without spawning.
        return {
            "action": "noop",
            "inputs": inputs,
            "context": {"establish_checkpoint": True, "agents_hash": current},
            "reason": "no prior checkpoint; establish baseline",
            "duplicate": False,
        }
    open_items = find_open_issues_with_marker(repo, MARKER_DOCS, gh_fn=gh_fn)
    if not open_items:
        open_items = find_open_prs_with_marker(repo, MARKER_DOCS, gh_fn=gh_fn)
    if open_items:
        return {
            "action": "noop",
            "inputs": inputs,
            "context": {"open_items": open_items},
            "reason": "open docs_drift Task/PR already exists",
            "duplicate": True,
        }
    return {
        "action": "spawn",
        "inputs": inputs,
        "context": {
            "agents_hash": current,
            "checkpoint_hash": checkpoint_hash,
            "marker": MARKER_DOCS,
        },
        "reason": "AGENTS/CLAUDE drifted from checkpoint",
        "duplicate": False,
    }


STALE_ITEMS_QUERY = """
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
                updatedAt
                issueType { name }
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


def fetch_stale_candidates(
    owner: str,
    number: int,
    *,
    stale_days: int,
    graphql_fn: Callable[..., dict[str, Any]],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return open board issues older than ``stale_days`` excluding Ready to ship."""
    from diff import normalize_status

    now = now or datetime.now(timezone.utc)
    cursor = None
    candidates: list[dict[str, Any]] = []
    while True:
        result = graphql_fn(
            STALE_ITEMS_QUERY,
            {"owner": owner, "number": number, "cursor": cursor},
        )
        project = (
            (result.get("data") or {})
            .get("organizationOrUser", {})
            .get("projectV2")
        )
        if not project:
            break
        items = project.get("items") or {}
        for node in items.get("nodes") or []:
            content = node.get("content") or {}
            if not content.get("number"):
                continue
            if content.get("state") != "OPEN":
                continue
            status_name = ((node.get("fieldValueByName") or {}).get("name")) or ""
            status = normalize_status(status_name)
            if status in ("ready_to_ship",):
                continue
            updated_raw = content.get("updatedAt")
            if not updated_raw:
                continue
            try:
                updated = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            age_days = (now - updated).total_seconds() / 86400.0
            if age_days < stale_days:
                continue
            repo = (content.get("repository") or {}).get("nameWithOwner") or ""
            candidates.append(
                {
                    "issue": f"{repo}#{content['number']}",
                    "repo": repo,
                    "number": content["number"],
                    "url": content.get("url"),
                    "title": content.get("title"),
                    "status": status,
                    "issue_type": (content.get("issueType") or {}).get("name"),
                    "updated_at": updated_raw,
                    "age_days": round(age_days, 1),
                }
            )
        page = items.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
    return candidates


def probe_stale_triage(
    *,
    owner: str,
    project_number: int,
    stale_days: int,
    graphql_fn: Callable[..., dict[str, Any]] | None = None,
    active_issues: set[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if graphql_fn is None:
        raise ValueError("graphql_fn is required for stale triage probe")
    candidates = fetch_stale_candidates(
        owner,
        project_number,
        stale_days=stale_days,
        graphql_fn=graphql_fn,
        now=now,
    )
    active_issues = active_issues or set()
    filtered = [c for c in candidates if c["issue"] not in active_issues]
    inputs = {
        "stale_days": stale_days,
        "issue_keys": sorted(c["issue"] for c in filtered),
    }
    if not filtered:
        return {
            "action": "noop",
            "inputs": inputs,
            "context": {"candidates": []},
            "reason": "no stale issues",
            "duplicate": False,
        }
    return {
        "action": "spawn",
        "inputs": inputs,
        "context": {"candidates": filtered, "marker": MARKER_STALE, "stale_days": stale_days},
        "reason": f"{len(filtered)} stale issue(s)",
        "duplicate": False,
    }


def check_aws_sso(
    profile: str,
    *,
    run_fn: Callable[..., subprocess.CompletedProcess] | None = None,
) -> dict[str, Any]:
    result = _run_cmd(
        ["aws", "sts", "get-caller-identity", "--profile", profile],
        run_fn=run_fn,
    )
    ok = result.returncode == 0
    return {
        "ok": ok,
        "profile": profile,
        "stdout": (result.stdout or "").strip()[:500],
        "stderr": (result.stderr or "").strip()[:500],
        "returncode": result.returncode,
    }


def probe_tier7_staging(
    *,
    repo_root: Path,
    aws_profile: str,
    run_fn: Callable[..., subprocess.CompletedProcess] | None = None,
) -> dict[str, Any]:
    import os

    auth = check_aws_sso(aws_profile, run_fn=run_fn)
    if not auth["ok"]:
        inputs = {"kind": "setup", "profile": aws_profile, "auth_ok": False}
        return {
            "action": "setup_alert",
            "inputs": inputs,
            "context": {"auth": auth, "marker": MARKER_TIER7_SETUP},
            "reason": "AWS SSO expired or profile missing",
            "duplicate": False,
        }

    merged = dict(os.environ)
    merged["AWS_PROFILE"] = aws_profile
    result = _run_cmd(
        ["bash", "scripts/test-tier7-monitor.sh"],
        cwd=repo_root,
        env=merged,
        run_fn=run_fn,
    )

    code = result.returncode
    stdout = (result.stdout or "")[:2000]
    stderr = (result.stderr or "")[:2000]
    if code == 0:
        return {
            "action": "noop",
            "inputs": {"kind": "healthy", "exit_code": 0},
            "context": {"stdout": stdout},
            "reason": "tier7 healthy",
            "duplicate": False,
        }
    if code == 2:
        return {
            "action": "setup_alert",
            "inputs": {"kind": "setup", "exit_code": 2},
            "context": {
                "stdout": stdout,
                "stderr": stderr,
                "marker": MARKER_TIER7_SETUP,
            },
            "reason": "tier7 SKIP — no local checks configured",
            "duplicate": False,
        }
    excerpt = (stderr or stdout or "tier7 failed")[:200]
    return {
        "action": "spawn",
        "inputs": {"kind": "anomaly", "exit_code": code, "excerpt": excerpt},
        "context": {
            "exit_code": code,
            "stdout": stdout,
            "stderr": stderr,
            "profile": aws_profile,
            "marker": MARKER_TIER7_ANOMALY,
        },
        "reason": f"tier7 anomaly exit={code}",
        "duplicate": False,
    }
