#!/usr/bin/env python3
"""
GitHub issue review — context gathering and Bug/Task sub-issue sync for /gh-review.

Usage:
  gh-review-publish.py preflight
  gh-review-publish.py context --issue OWNER/REPO#N | URL [--output PATH]
  gh-review-publish.py init-payload --context context.json [-o payload.json]
  gh-review-publish.py init-triage-doc --context context.json [-o path] [--force]
  gh-review-publish.py resolve-target --context context.json [-o target.json]
  gh-review-publish.py validate-payload --input payload.json
  gh-review-publish.py check-consistency --input payload.json [--triage path]
  gh-review-publish.py sync-bugs --input payload.json [--dry-run]
  gh-review-publish.py comment --input payload.json --sync-summary sync.json
  gh-review-publish.py publish --input payload.json [-o sync.json] [--dry-run]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_COMMANDS_ROOT = _SCRIPT_DIR.parent.parent
_TEMPLATE_DIR = _COMMANDS_ROOT / "_templates" / "gh-review"
_REPO_ROOT = _COMMANDS_ROOT.parent.parent
_TRIAGE_TEMPLATE_PATH = _REPO_ROOT / "docs" / "paperwork" / "gh-review-triage.md.template"
_SPEC_PUBLISH_PATH = _SCRIPT_DIR / "gh-spec-publish.py"

VALID_AGGREGATE_VERDICTS = frozenset({"FAIL", "PASS_WITH_NOTES", "PASS"})
VALID_DISPOSITIONS = frozenset({"CONFIRM", "TRACK", "DISMISS"})
VALID_SEVERITIES = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW"})
VALID_DISMISS_REASONS = frozenset(
    {"wrong-fact", "hypothetical", "intentional", "out-of-scope"}
)
INVALID_DISMISS_REASONS = frozenset({"hygiene", "test-hygiene"})

_spec = importlib.util.spec_from_file_location("gh_spec_publish", _SPEC_PUBLISH_PATH)
assert _spec and _spec.loader
_gsp = importlib.util.module_from_spec(_spec)
sys.modules["gh_spec_publish"] = _gsp
_spec.loader.exec_module(_gsp)

IssueRef = _gsp.IssueRef
add_sub_issue = _gsp.add_sub_issue
create_issue = _gsp.create_issue
edit_issue = _gsp.edit_issue
ensure_issue_type = _gsp.ensure_issue_type
gh_json = _gsp.gh_json
gh_run = _gsp.gh_run
graphql = _gsp.graphql
issue_ref = _gsp.issue_ref
parse_issue_url = _gsp.parse_issue_url
parse_repo = _gsp.parse_repo
sub_issues_supported = _gsp.sub_issues_supported
utc_now_iso = _gsp.utc_now_iso

ISSUE_SPEC_PATTERN = re.compile(
    r"^(?:https://github\.com/)?(?P<owner>[^/#]+)/(?P<repo>[^/#]+)#(?P<number>\d+)$"
)
PARENT_SPEC_PATTERN = re.compile(r"Parent spec:\s*#(\d+)", re.IGNORECASE)
STORY_PATTERN = re.compile(r"Story:\s*([A-Z]{2}-\d+).*?#(\d+)", re.IGNORECASE)
RR_ID_TITLE_PATTERN = re.compile(r"^\[(RR-\d+)\]\s*(.+)$", re.IGNORECASE)
RR_ID_BODY_PATTERN = re.compile(r"\*\*Finding ID:\*\*\s*(RR-\d+)", re.IGNORECASE)
RR_ID_NUMBER_PATTERN = re.compile(r"^RR-(\d+)$", re.IGNORECASE)
DISPOSITION_BODY_PATTERN = re.compile(
    r"\*\*Disposition:\*\*\s*(\w+)", re.IGNORECASE
)
REVIEW_HISTORY_MARKER = "## Review history"
PARENT_COMMENT_MARKER = "## gh-review summary"
USER_STORY_ISSUE_TYPE = "user story"
SUMMARY_WORD_OVERLAP_THRESHOLD = 0.4


def is_user_story_issue(issue_type: str | None) -> bool:
    return (issue_type or "").strip().lower() == USER_STORY_ISSUE_TYPE


def review_issue_dict(
    *,
    repo: str,
    number: int,
    issue: dict[str, Any],
) -> dict[str, Any]:
    return {
        "repo": repo,
        "number": number,
        "title": issue.get("title"),
        "url": issue.get("url"),
        "state": issue.get("state"),
        "issue_type": (issue.get("issueType") or {}).get("name"),
    }


def resolve_story_issue_from_graph(
    *,
    repo: str,
    number: int,
    issue: dict[str, Any],
    parent_issues: list[dict[str, Any]],
    story_match: re.Match[str] | None,
) -> dict[str, Any] | None:
    """User story linked to the reviewed issue for AC/context in finding bodies.

    TRACK Task sub-issues always attach to the reviewed (input) issue — not this
    story and not the Spec/epic parent. This field is traceability only.
    """
    if is_user_story_issue((issue.get("issueType") or {}).get("name")):
        return review_issue_dict(repo=repo, number=number, issue=issue)

    if parent_issues:
        return dict(parent_issues[0])

    if story_match:
        story_num = int(story_match.group(2))
        try:
            story_ref_obj = issue_ref(repo, story_num)
            story_data = gh_json(
                [
                    "issue",
                    "view",
                    str(story_num),
                    "--repo",
                    repo,
                    "--json",
                    "number,title,url,state",
                ]
            )
            return {
                "repo": repo,
                "number": story_num,
                "title": story_data.get("title"),
                "url": story_ref_obj.url,
                "state": story_data.get("state"),
            }
        except subprocess.CalledProcessError:
            pass

    return None


ISSUE_CONTEXT_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      number
      title
      url
      state
      body
      issueType { name }
      parent {
        number
        title
        url
        state
        repository { nameWithOwner }
      }
      subIssues(first: 100) {
        nodes {
          number
          title
          url
          state
          body
          issueType { name }
          repository { nameWithOwner }
        }
      }
    }
  }
}
"""

CLOSE_ISSUE_MUTATION = """
mutation($issueId: ID!) {
  closeIssue(input: { issueId: $issueId }) {
    issue { number state }
  }
}
"""


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


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


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | None, data: dict[str, Any]) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if path:
        Path(path).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def template_path(name: str) -> Path:
    path = _TEMPLATE_DIR / name
    if not path.exists():
        raise SystemExit(f"template not found: {path}")
    return path


def read_template(name: str) -> str:
    return template_path(name).read_text(encoding="utf-8")


def render_template(text: str, values: dict[str, str]) -> str:
    out = text
    for key, value in values.items():
        out = out.replace(f"{{{{{key}}}}}", value)
    return out


def slugify(text: str, *, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").lower()).strip("-")
    return (slug[:max_len] if slug else "review").strip("-")


def feature_slug_from_context(context: dict[str, Any]) -> str:
    scope = context.get("scope_hints") or {}
    spec_path = scope.get("spec_path") or ""
    if spec_path:
        parts = Path(spec_path).parts
        if "specs" in parts:
            idx = parts.index("specs")
            if idx + 1 < len(parts):
                return slugify(parts[idx + 1], max_len=64)
        return slugify(Path(spec_path).parent.name, max_len=64)
    review = context.get("review_issue") or {}
    return slugify(review.get("title") or "review", max_len=64)


def suggest_triage_path(context: dict[str, Any]) -> str:
    review = context.get("review_issue") or {}
    number = review.get("number") or 0
    feature = feature_slug_from_context(context)
    title_slug = slugify(review.get("title") or "review", max_len=32)
    return f"docs/paperwork/{feature}/gh-review-{number}-{title_slug}.md"


def build_init_payload(context: dict[str, Any]) -> dict[str, Any]:
    review_issue = context.get("review_issue") or {}
    linked_prs = context.get("linked_prs") or []
    payload: dict[str, Any] = {
        "review_issue": {
            "repo": review_issue.get("repo"),
            "number": review_issue.get("number"),
            "url": review_issue.get("url"),
            "title": review_issue.get("title"),
        },
        "review_date": utc_today(),
        "triage_path": suggest_triage_path(context),
        "aggregate_verdict": "PASS_WITH_NOTES",
        "issue_type": "Bug",
        "followup_issue_type": "Task",
        "findings": [],
        "branches": context.get("branches") or [],
    }
    if context.get("story_issue"):
        payload["story_issue"] = context["story_issue"]
    if linked_prs:
        payload["pr"] = linked_prs[0]
    if context.get("parent_issues"):
        payload["parent_issues"] = context["parent_issues"]
    if context.get("scope_hints"):
        payload["scope_hints"] = context["scope_hints"]
    if context.get("rr_id_registry"):
        payload["rr_id_registry"] = context["rr_id_registry"]
    return payload


def resolve_review_target(context: dict[str, Any]) -> dict[str, Any]:
    review_issue = context.get("review_issue") or {}
    default_repo = review_issue.get("repo") or ""
    linked_prs = context.get("linked_prs") or []
    if linked_prs:
        pr = linked_prs[0]
        return {
            "type": "pr",
            "repo": pr.get("repo") or default_repo,
            "ref": pr.get("head_ref"),
            "base_ref": pr.get("base_ref"),
            "number": pr.get("number"),
            "url": pr.get("url"),
            "paths": [],
        }
    branches = context.get("branches") or []
    if branches:
        branch = branches[0]
        return {
            "type": "branch",
            "repo": branch.get("repo") or default_repo,
            "ref": branch.get("branch"),
            "base_ref": branch.get("base"),
            "paths": [],
        }
    return {
        "type": "none",
        "repo": default_repo,
        "ref": None,
        "base_ref": None,
        "paths": [],
        "gate": "No PR, branch, or resolvable file scope — stop and ask.",
    }


def validate_payload(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    for field in (
        "review_issue",
        "review_date",
        "triage_path",
        "aggregate_verdict",
        "findings",
        "branches",
        "issue_type",
        "followup_issue_type",
    ):
        if field not in payload:
            errors.append(f"Missing required field: {field}")

    review_issue = payload.get("review_issue") or {}
    if not review_issue.get("repo"):
        errors.append("review_issue.repo is required")
    if not review_issue.get("number"):
        errors.append("review_issue.number is required")

    review_date = payload.get("review_date") or ""
    if review_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", review_date):
        errors.append(f"review_date must be YYYY-MM-DD, got {review_date!r}")

    verdict = payload.get("aggregate_verdict")
    if verdict and verdict not in VALID_AGGREGATE_VERDICTS:
        errors.append(
            f"aggregate_verdict must be one of {sorted(VALID_AGGREGATE_VERDICTS)}"
        )

    if payload.get("issue_type") and payload.get("issue_type") != "Bug":
        errors.append('issue_type must be "Bug"')
    if payload.get("followup_issue_type") and payload.get("followup_issue_type") != "Task":
        errors.append('followup_issue_type must be "Task"')

    repos_touched = (payload.get("scope_hints") or {}).get("repos_touched") or []
    multi_repo = len(repos_touched) > 1

    findings = payload.get("findings")
    if findings is not None and not isinstance(findings, list):
        errors.append("findings must be an array")

    warnings.extend(validate_payload_duplicate_rr_ids(findings or []))

    for idx, finding in enumerate(findings or []):
        prefix = f"findings[{idx}]"
        fid = (finding.get("id") or "").upper()
        if not re.match(r"^RR-\d+$", fid):
            errors.append(f"{prefix}.id must match RR-NN, got {finding.get('id')!r}")

        disposition = (finding.get("disposition") or "").upper()
        if disposition not in VALID_DISPOSITIONS:
            errors.append(
                f"{prefix}.disposition must be CONFIRM|TRACK|DISMISS, got {disposition!r}"
            )

        severity = (finding.get("severity") or "").upper()
        if severity not in VALID_SEVERITIES:
            errors.append(
                f"{prefix}.severity must be CRITICAL|HIGH|MEDIUM|LOW, got {severity!r}"
            )

        for req in ("summary", "rationale", "recommendation"):
            if not (finding.get(req) or "").strip():
                errors.append(f"{prefix}.{req} is required")

        evidence = finding.get("evidence")
        if not evidence or not isinstance(evidence, list):
            errors.append(f"{prefix}.evidence must be a non-empty string array")
        elif not any(str(item).strip() for item in evidence):
            errors.append(f"{prefix}.evidence must contain at least one non-empty item")

        if disposition == "DISMISS":
            reason = (finding.get("dismiss_reason") or "").strip().lower()
            if not reason:
                errors.append(f"{prefix}.dismiss_reason is required for DISMISS")
            elif reason in INVALID_DISMISS_REASONS:
                errors.append(
                    f"{prefix}.dismiss_reason {reason!r} is invalid — use TRACK with "
                    f"track_reason instead"
                )
            elif reason not in VALID_DISMISS_REASONS:
                errors.append(
                    f"{prefix}.dismiss_reason must be one of "
                    f"{sorted(VALID_DISMISS_REASONS)}"
                )

        if disposition in {"CONFIRM", "TRACK"}:
            if not (finding.get("repo") or "").strip():
                if multi_repo:
                    warnings.append(
                        f"{prefix} ({fid}): repo omitted with multiple repos_touched — "
                        "defaults to review_issue.repo"
                    )
                else:
                    warnings.append(
                        f"{prefix} ({fid}): repo omitted — defaults to review_issue.repo"
                    )

    branches = payload.get("branches")
    if isinstance(branches, list) and not branches:
        warnings.append("branches[] is empty — copy from context when input issue has Development branches")

    return errors, warnings


def extract_rr_ids_from_text(text: str) -> set[str]:
    return {match.group(1).upper() for match in re.finditer(r"\b(RR-\d+)\b", text, re.I)}


def check_payload_triage_consistency(
    payload: dict[str, Any], triage_path: Path
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not triage_path.exists():
        errors.append(f"Triage file not found: {triage_path}")
        return errors, warnings

    triage_text = triage_path.read_text(encoding="utf-8")
    payload_ids = {
        (f.get("id") or "").upper()
        for f in (payload.get("findings") or [])
        if f.get("id")
    }
    triage_ids = extract_rr_ids_from_text(triage_text)

    missing_in_triage = sorted(payload_ids - triage_ids)
    missing_in_payload = sorted(triage_ids - payload_ids)

    for rr_id in missing_in_triage:
        errors.append(f"{rr_id} in payload but not found in triage doc")
    for rr_id in missing_in_payload:
        warnings.append(f"{rr_id} in triage doc but not in payload findings[]")

    return errors, warnings


def render_init_triage_doc(context: dict[str, Any], triage_path: str) -> str:
    review = context.get("review_issue") or {}
    scope = context.get("scope_hints") or {}
    linked_prs = context.get("linked_prs") or []
    branches = context.get("branches") or []
    story = context.get("story_issue") or {}

    branch_bits: list[str] = []
    for row in branches:
        base = f" (base: `{row.get('base')}`)" if row.get("base") else ""
        branch_bits.append(f"`{row.get('repo')}`:`{row.get('branch')}`{base}")
    if linked_prs and not branch_bits:
        pr = linked_prs[0]
        branch_bits.append(
            f"PR #{pr.get('number')} `{pr.get('head_ref')}` → `{pr.get('base_ref')}`"
        )

    context_bits = [f"Reviewed issue #{review.get('number')}"]
    if story.get("number"):
        context_bits.append(f"story #{story.get('number')}")
    if linked_prs:
        context_bits.append(f"PR #{linked_prs[0].get('number')}")

    placeholder_finding = render_template(
        read_template("finding-section.md.template"),
        {
            "ID": "RR-01",
            "TITLE": "[one-line summary]",
            "SEVERITY": "HIGH",
            "DISPOSITION": "CONFIRM|TRACK|DISMISS",
            "REASON": "[dismiss_reason or track_reason]",
            "OWNER": "SA1",
            "REPO": "owner/repo",
            "FINDING": "[what was claimed]",
            "WHERE": "path:line",
            "PLAN_SPEC": "[quotes or links]",
            "WHY": "[evidence]",
            "MITIGATION": "[if any]",
            "RECOMMENDATION": "[fix direction]",
        },
    )

    return render_template(
        _TRIAGE_TEMPLATE_PATH.read_text(encoding="utf-8"),
        {
            "TITLE": review.get("title") or "Review",
            "ISSUE_NUMBER": str(review.get("number") or ""),
            "ISSUE_TITLE": review.get("title") or "",
            "ISSUE_URL": review.get("url") or "",
            "BRANCH_COMMITS": ", ".join(branch_bits) if branch_bits else "…",
            "REVIEW_DATE": utc_today(),
            "CONTEXT": "; ".join(context_bits),
            "SCOPE_REMINDER": "- **In scope:** …\n- **Out of scope:** …",
            "VERIFICATION_RUN": "_(commands + pass/fail, if any)_",
            "DISPOSITION_LEGEND": read_template("disposition-legend.md").strip(),
            "PLAN_ANCHORS": f"- Spec: `{scope.get('spec_path') or '…'}`",
            "SUGGESTED_ACTION_ORDER": "_(blockers → same PR → defer → close)_",
            "FINDING_SECTIONS": placeholder_finding.strip(),
            "SPEC_PATH": scope.get("spec_path") or "…",
            "TRIAGE_PATH": triage_path,
        },
    )


def parse_repos_touched(body: str) -> list[str]:
    repos: list[str] = []
    in_section = False
    for line in body.splitlines():
        if re.match(r"^##\s+Repositories touched", line, re.IGNORECASE):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            match = re.search(r"`([^`]+/[^`]+)`", line)
            if match:
                repos.append(match.group(1))
    return repos


def parse_development_branches(body: str) -> list[dict[str, str]]:
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
        base = cells[2].strip("` ") if len(cells) > 2 else ""
        if "/" in repo and branch:
            entry: dict[str, str] = {"repo": repo, "branch": branch}
            if base:
                entry["base"] = base
            branches.append(entry)
    return branches


def parse_spec_path(body: str) -> str | None:
    for pattern in (
        r"`(docs/specs/[^`\s]+/SPEC\.md)`",
        r"(docs/specs/[^\s)]+/SPEC\.md)",
    ):
        match = re.search(pattern, body)
        if match:
            return match.group(1)
    return None


def _pr_entry(item: dict[str, Any], default_repo: str) -> dict[str, Any]:
    pr_repo = (item.get("repository") or {}).get("nameWithOwner") or default_repo
    return {
        "repo": pr_repo,
        "number": item.get("number"),
        "title": item.get("title"),
        "url": item.get("url"),
        "state": item.get("state"),
        "head_ref": item.get("headRefName"),
        "base_ref": item.get("baseRefName"),
    }


def list_linked_prs(repo: str, issue_number: int) -> list[dict[str, Any]]:
    owner, name = parse_repo(repo)
    query = f"repo:{owner}/{name} linked:issue-{issue_number}"
    try:
        data = gh_json(
            [
                "search",
                "prs",
                query,
                "--json",
                "number,title,url,state,headRefName,baseRefName,repository",
                "--limit",
                "20",
            ]
        )
    except subprocess.CalledProcessError:
        return []
    prs: list[dict[str, Any]] = []
    for item in data or []:
        prs.append(_pr_entry(item, repo))
    return prs


def find_open_pr_by_head(repo: str, head_branch: str) -> dict[str, Any] | None:
    """Return an open PR whose head branch matches ``head_branch`` on ``repo``."""
    owner, _name = parse_repo(repo)
    head_spec = f"{owner}:{head_branch}"
    try:
        data = gh_json(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--head",
                head_spec,
                "--state",
                "open",
                "--json",
                "number,title,url,state,headRefName,baseRefName",
                "--limit",
                "5",
            ]
        )
    except subprocess.CalledProcessError:
        return None
    for item in data or []:
        if item.get("headRefName") == head_branch:
            return _pr_entry(item, repo)
    if data:
        return _pr_entry(data[0], repo)
    return None


ISSUE_REF_PATTERNS = [
    re.compile(r"(?:[\w.-]+/[\w.-]+)?#(\d+)\b"),
    re.compile(r"github\.com/[\w.-]+/[\w.-]+/issues/(\d+)\b", re.IGNORECASE),
]


def pr_body_references_issue(body: str, issue_number: int) -> bool:
    target = str(issue_number)
    for pattern in ISSUE_REF_PATTERNS:
        for match in pattern.finditer(body or ""):
            if match.group(1) == target:
                return True
    return False


def find_pr_by_issue_ref_in_body(
    repo: str,
    issue_number: int,
    *,
    task_branch: str | None = None,
    limit: int = 30,
) -> dict[str, Any] | None:
    """Scan open PR bodies on ``repo`` for references to ``issue_number``."""
    try:
        data = gh_json(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--json",
                "number,title,url,state,headRefName,baseRefName,body",
                "--limit",
                str(limit),
            ]
        )
    except subprocess.CalledProcessError:
        return None
    head_match: dict[str, Any] | None = None
    fallback: dict[str, Any] | None = None
    for item in data or []:
        if not pr_body_references_issue(item.get("body") or "", issue_number):
            continue
        entry = _pr_entry(item, repo)
        if task_branch and entry.get("head_ref") == task_branch:
            head_match = entry
            break
        if fallback is None:
            fallback = entry
    return head_match or fallback


def list_issue_develop_branches(repo: str, issue_number: int) -> list[str]:
    try:
        result = _gsp._run_gh(
            ["issue", "develop", str(issue_number), "--repo", repo, "--list"]
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    names: list[str] = []
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if line:
            names.append(line)
    return names


def issue_graph(repo: str, number: int) -> dict[str, Any]:
    owner, name = parse_repo(repo)
    try:
        data = _gsp.graphql_with_features(
            ISSUE_CONTEXT_QUERY,
            {"owner": owner, "name": name, "number": number},
            features="sub_issues,issue_types",
        )
    except subprocess.CalledProcessError:
        data = gh_json(
            [
                "issue",
                "view",
                str(number),
                "--repo",
                repo,
                "--json",
                "number,title,url,state,body",
            ]
        )
        issue = {
            "number": data.get("number"),
            "title": data.get("title"),
            "url": data.get("url"),
            "state": data.get("state"),
            "body": data.get("body") or "",
            "issueType": None,
            "parent": None,
            "subIssues": {"nodes": _list_sub_issues_rest(repo, number)},
        }
        return issue

    issue = data.get("data", {}).get("repository", {}).get("issue")
    if not issue:
        raise SystemExit(f"issue not found: {repo}#{number}")
    return issue


def _list_sub_issues_rest(repo: str, number: int) -> list[dict[str, Any]]:
    owner, name = parse_repo(repo)
    try:
        nodes = gh_json(
            ["api", f"repos/{owner}/{name}/issues/{number}/sub_issues"]
        )
    except subprocess.CalledProcessError:
        return []
    if not isinstance(nodes, list):
        return []
    out: list[dict[str, Any]] = []
    for node in nodes:
        repo_full = (node.get("repository") or {}).get("nameWithOwner")
        if not repo_full:
            repo_full = repo
        out.append(
            {
                "number": node.get("number"),
                "title": node.get("title"),
                "url": node.get("html_url") or node.get("url"),
                "state": node.get("state"),
                "body": node.get("body") or "",
                "issueType": None,
                "repository": {"nameWithOwner": repo_full},
            }
        )
    return out


def cmd_preflight(_args: argparse.Namespace) -> int:
    supported = sub_issues_supported()
    print(f"sub_issues: {'supported' if supported else 'unavailable'}")
    print(f"bug_issue_type: Bug (org issue type required at publish)")
    print(f"followup_issue_type: Task (org issue type required for TRACK findings)")
    return 0 if supported else 1


def cmd_context(args: argparse.Namespace) -> int:
    repo, number = parse_issue_spec(args.issue, default_repo=args.repo)
    issue = issue_graph(repo, number)
    body = issue.get("body") or ""

    parent_issues: list[dict[str, Any]] = []
    parent = issue.get("parent")
    if parent:
        parent_issues.append(
            {
                "repo": parent.get("repository", {}).get("nameWithOwner"),
                "number": parent.get("number"),
                "title": parent.get("title"),
                "url": parent.get("url"),
                "state": parent.get("state"),
            }
        )

    parent_match = PARENT_SPEC_PATTERN.search(body)
    if parent_match:
        parent_num = int(parent_match.group(1))
        if not any(p.get("number") == parent_num for p in parent_issues):
            try:
                pref = issue_ref(repo, parent_num)
                pdata = gh_json(
                    [
                        "issue",
                        "view",
                        str(parent_num),
                        "--repo",
                        repo,
                        "--json",
                        "number,title,url,state,body",
                    ]
                )
                parent_issues.append(
                    {
                        "repo": repo,
                        "number": parent_num,
                        "title": pdata.get("title"),
                        "url": pref.url,
                        "state": pdata.get("state"),
                    }
                )
            except subprocess.CalledProcessError:
                pass

    sub_issues = []
    for node in (issue.get("subIssues") or {}).get("nodes") or []:
        sub_issues.append(
            {
                "repo": node.get("repository", {}).get("nameWithOwner"),
                "number": node.get("number"),
                "title": node.get("title"),
                "url": node.get("url"),
                "state": node.get("state"),
                "body": node.get("body") or "",
                "issue_type": (node.get("issueType") or {}).get("name"),
            }
        )

    branches = parse_development_branches(body)
    develop_names = list_issue_develop_branches(repo, number)
    if develop_names and not branches:
        for name in develop_names:
            branches.append({"repo": repo, "branch": name})

    linked_prs = list_linked_prs(repo, number)
    repos_touched = parse_repos_touched(body)
    spec_path = parse_spec_path(body)

    manifest_path = None
    if spec_path:
        candidate = Path(spec_path).parent / "gh-spec.manifest.json"
        manifest_path = str(candidate)

    story_match = STORY_PATTERN.search(body)
    review_issue = review_issue_dict(repo=repo, number=number, issue=issue)
    story_issue = resolve_story_issue_from_graph(
        repo=repo,
        number=number,
        issue=issue,
        parent_issues=parent_issues,
        story_match=story_match,
    )

    rr_id_registry = build_rr_id_registry(sub_issues)

    payload = {
        "review_issue": review_issue,
        "story_issue": story_issue,
        "parent_issues": parent_issues,
        "sub_issues": sub_issues,
        "rr_id_registry": rr_id_registry,
        "linked_prs": linked_prs,
        "branches": branches,
        "scope_hints": {
            "repos_touched": repos_touched,
            "spec_path": spec_path,
            "manifest_path": manifest_path,
            "story_id": story_match.group(1) if story_match else None,
            "story_issue_number": (
                int(story_issue["number"])
                if story_issue and story_issue.get("number") is not None
                else (int(story_match.group(2)) if story_match else None)
            ),
        },
        "sub_issues_supported": sub_issues_supported(),
        "gathered_at": utc_now_iso(),
    }
    write_json(args.output, payload)
    return 0


def finding_title(finding: dict[str, Any]) -> str:
    summary = (finding.get("summary") or "Review finding").strip()
    if len(summary) > 120:
        summary = summary[:117] + "..."
    return f"[{finding['id']}] {summary}"


def format_paths_table(paths: list[dict[str, Any]]) -> str:
    if not paths:
        return "_None listed_"
    lines = ["| Path | Role |", "|------|------|"]
    for row in paths:
        path = row.get("path") or row.get("file") or ""
        role = row.get("role") or row.get("note") or ""
        lines.append(f"| `{path}` | {role} |")
    return "\n".join(lines)


def format_branches_table(branches: list[dict[str, Any]]) -> str:
    if not branches:
        return "_None linked_"
    lines = ["| Repo | Branch | Base |", "|------|--------|------|"]
    for row in branches:
        lines.append(
            f"| `{row.get('repo', '')}` | `{row.get('branch', '')}` | "
            f"`{row.get('base', '')}` |"
        )
    return "\n".join(lines)


def format_evidence(evidence: list[str]) -> str:
    if not evidence:
        return "- _No evidence recorded_"
    return "\n".join(f"- {item}" for item in evidence)


def render_finding_body(
    finding: dict[str, Any],
    payload: dict[str, Any],
    *,
    is_update: bool = False,
    prior_body: str | None = None,
) -> str:
    review_issue = payload["review_issue"]
    story_issue = payload.get("story_issue") or {}
    branches = finding.get("branches") or payload.get("branches") or []
    pr = payload.get("pr")
    triage_path = payload.get("triage_path") or ""
    review_date = payload.get("review_date") or utc_today()
    disposition = (finding.get("disposition") or "CONFIRM").upper()
    track_reason = (finding.get("track_reason") or "").strip()
    track_line = f"\n**Track reason:** {track_reason}" if track_reason else ""

    reproduction = (finding.get("reproduction") or "").strip()
    repro_section = ""
    if reproduction:
        repro_section = f"\n## Reproduction\n\n{reproduction}\n"

    pr_line = "_None linked_"
    if pr:
        pr_line = f"#{pr.get('number')} — {pr.get('url', '')}"

    story_line = "_None linked_"
    if story_issue.get("number"):
        story_line = (
            f"#{story_issue.get('number')} — {story_issue.get('title', '')} "
            f"({story_issue.get('url', '')})"
        )

    body = f"""## Finding

**Finding ID:** {finding['id']}
**Summary:** {finding.get('summary', '')}

**Severity:** {finding.get('severity', 'MEDIUM')}
**Disposition:** {disposition}{track_line}
**Review date:** {review_date}
**Owner (surface area):** {finding.get('owner_sa') or '—'}

## Summary

{(finding.get('rationale') or finding.get('summary') or '').strip()}

## Evidence

{format_evidence(finding.get('evidence') or [])}

## Involved code

{format_paths_table(finding.get('paths') or [])}
{repro_section}
## Branches (from input issue #{review_issue.get('number')})

{format_branches_table(branches)}

## Linked context

- **Reviewed issue:** #{review_issue.get('number')} — {review_issue.get('title', '')} ({review_issue.get('url', '')})
- **User story:** {story_line}
- **PR:** {pr_line}
- **Triage doc:** `{triage_path}`

## Recommendation

{(finding.get('recommendation') or '—').strip()}
"""
    if is_update and prior_body:
        history = extract_review_history(prior_body)
        history = upsert_review_history_entry(
            history,
            review_date=review_date,
            disposition=disposition,
            severity=finding.get("severity", "MEDIUM"),
        )
        body = body.rstrip() + "\n\n" + REVIEW_HISTORY_MARKER + "\n\n" + "\n".join(history)
    return body.rstrip() + "\n"


def review_history_entry(
    *,
    review_date: str,
    disposition: str,
    severity: str,
) -> str:
    return (
        f"### {review_date}\n"
        f"- Re-reviewed; disposition **{disposition}**\n"
        f"- Severity: {severity}\n"
    )


def upsert_review_history_entry(
    history: list[str],
    *,
    review_date: str,
    disposition: str,
    severity: str,
) -> list[str]:
    """Replace same-day history on re-run instead of appending duplicates."""
    entry = review_history_entry(
        review_date=review_date,
        disposition=disposition,
        severity=severity,
    )
    updated = list(history)
    for index, existing in enumerate(updated):
        if existing.startswith(f"### {review_date}"):
            updated[index] = entry
            return updated
    updated.append(entry)
    return updated


def extract_review_history(body: str) -> list[str]:
    if REVIEW_HISTORY_MARKER not in body:
        return []
    _, rest = body.split(REVIEW_HISTORY_MARKER, 1)
    chunks = [c.strip() for c in rest.strip().split("### ") if c.strip()]
    return [f"### {c}" if not c.startswith("###") else c for c in chunks]


def extract_rr_id(title: str, body: str = "") -> str | None:
    match = RR_ID_TITLE_PATTERN.match(title.strip())
    if match:
        return match.group(1).upper()
    body_match = RR_ID_BODY_PATTERN.search(body)
    if body_match:
        return body_match.group(1).upper()
    return None


def parse_rr_number(rr_id: str) -> int | None:
    match = RR_ID_NUMBER_PATTERN.match(rr_id.strip().upper())
    return int(match.group(1)) if match else None


def format_rr_id(number: int) -> str:
    return f"RR-{number:02d}"


def title_summary_from_issue(title: str) -> str:
    match = RR_ID_TITLE_PATTERN.match(title.strip())
    if match:
        return match.group(2).strip()
    return title.strip()


def disposition_from_body(body: str) -> str | None:
    match = DISPOSITION_BODY_PATTERN.search(body or "")
    if match:
        return match.group(1).upper()
    return None


def finding_summaries_compatible(
    existing_title: str,
    existing_body: str,
    new_summary: str,
) -> bool:
    old_sum = title_summary_from_issue(existing_title).lower()
    new_sum = (new_summary or "").strip().lower()
    if not old_sum or not new_sum:
        return True
    if old_sum == new_sum:
        return True
    if old_sum in new_sum or new_sum in old_sum:
        return True
    old_words = {w for w in re.split(r"\W+", old_sum) if len(w) > 3}
    new_words = {w for w in re.split(r"\W+", new_sum) if len(w) > 3}
    if not old_words or not new_words:
        return True
    overlap = len(old_words & new_words) / min(len(old_words), len(new_words))
    return overlap >= SUMMARY_WORD_OVERLAP_THRESHOLD


def should_update_existing(
    existing: dict[str, Any],
    finding: dict[str, Any],
) -> tuple[bool, str | None]:
    state = (existing.get("state") or "").upper()
    if state == "CLOSED":
        return False, "existing_closed"
    if not finding_summaries_compatible(
        existing.get("title") or "",
        existing.get("body") or "",
        finding.get("summary") or "",
    ):
        return False, "summary_mismatch"
    return True, None


def collect_rr_registry_entries(
    sub_issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for node in sub_issues:
        rr_id = extract_rr_id(node.get("title") or "", node.get("body") or "")
        if not rr_id:
            continue
        entries.append(
            {
                "id": rr_id,
                "number": node.get("number"),
                "state": node.get("state"),
                "title": node.get("title"),
                "issue_type": node.get("issue_type") or node.get("issueType"),
            }
        )
    return entries


def build_rr_id_registry(sub_issues: list[dict[str, Any]]) -> dict[str, Any]:
    entries = collect_rr_registry_entries(sub_issues)
    numbers = [
        n for n in (parse_rr_number(entry["id"]) for entry in entries) if n is not None
    ]
    max_number = max(numbers) if numbers else 0
    entries.sort(key=lambda row: parse_rr_number(row["id"]) or 0)
    return {
        "existing": entries,
        "max_number": max_number,
        "next_id": format_rr_id(max_number + 1) if max_number else "RR-01",
    }


def allocate_next_rr_id(
    *,
    used_ids: set[str],
    sub_issues: list[dict[str, Any]],
) -> str:
    numbers: set[int] = set()
    for rr_id in used_ids:
        parsed = parse_rr_number(rr_id)
        if parsed is not None:
            numbers.add(parsed)
    for node in sub_issues:
        rr_id = extract_rr_id(node.get("title") or "", node.get("body") or "")
        if rr_id:
            parsed = parse_rr_number(rr_id)
            if parsed is not None:
                numbers.add(parsed)
    next_number = (max(numbers) + 1) if numbers else 1
    while format_rr_id(next_number) in used_ids:
        next_number += 1
    return format_rr_id(next_number)


def detect_rr_id_collisions(sub_issues: list[dict[str, Any]]) -> list[str]:
    by_id: dict[str, list[int]] = {}
    for node in sub_issues:
        rr_id = extract_rr_id(node.get("title") or "", node.get("body") or "")
        if not rr_id:
            continue
        number = node.get("number")
        if number is not None:
            by_id.setdefault(rr_id, []).append(int(number))
    warnings: list[str] = []
    for rr_id, numbers in sorted(by_id.items()):
        if len(numbers) > 1:
            refs = ", ".join(f"#{n}" for n in numbers)
            warnings.append(
                f"Duplicate RR-ID {rr_id} on sub-issues {refs}; "
                f"sync matches the last one indexed only"
            )
    return warnings


def validate_payload_duplicate_rr_ids(findings: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    warnings: list[str] = []
    for finding in findings:
        rr_id = (finding.get("id") or "").upper()
        if not rr_id:
            continue
        if rr_id in seen:
            warnings.append(f"Payload lists RR-ID {rr_id} more than once")
        seen.add(rr_id)
    return warnings


def resolve_existing_for_sync(
    existing: dict[str, Any] | None,
    finding: dict[str, Any],
    *,
    sub_issues: list[dict[str, Any]],
    used_ids: set[str],
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str], dict[str, Any] | None]:
    """Decide update vs create; reallocate RR-ID when overwrite would be unsafe.

    Returns superseded existing sub-issue when a new ID is created to avoid overwrite.
    """
    warnings: list[str] = []
    effective = dict(finding)
    requested_id = (finding.get("id") or "").upper()

    if not existing:
        used_ids.add(requested_id)
        return None, effective, warnings, None

    should_update, reason = should_update_existing(existing, finding)
    if should_update:
        used_ids.add(requested_id)
        return existing, effective, warnings, None

    new_id = allocate_next_rr_id(used_ids=used_ids, sub_issues=sub_issues)
    used_ids.add(new_id)
    effective["id"] = new_id
    superseded = existing

    if reason == "existing_closed":
        warnings.append(
            f"{requested_id} matched closed sub-issue #{existing.get('number')}; "
            f"created {new_id} instead of overwriting"
        )
        superseded = None
    elif reason == "summary_mismatch":
        warnings.append(
            f"{requested_id} matched open sub-issue #{existing.get('number')} "
            f"but summary differs materially; created {new_id} instead of overwriting"
        )
    else:
        warnings.append(
            f"{requested_id} could not update sub-issue #{existing.get('number')}; "
            f"created {new_id}"
        )
        superseded = None

    return None, effective, warnings, superseded


def sub_issues_missing_issue_types(sub_issues: list[dict[str, Any]]) -> bool:
    rr_nodes = [
        node
        for node in sub_issues
        if extract_rr_id(node.get("title") or "", node.get("body") or "")
    ]
    if not rr_nodes:
        return False
    return all(not (node.get("issue_type") or node.get("issueType")) for node in rr_nodes)


def is_rr_sub_issue(node: dict[str, Any], *, kind: str) -> bool:
    issue_type = (node.get("issue_type") or node.get("issueType") or "").strip().lower()
    title = node.get("title") or ""
    body = node.get("body") or ""
    has_rr_title = bool(RR_ID_TITLE_PATTERN.match(title))
    has_rr_body = bool(RR_ID_BODY_PATTERN.search(body))
    if not has_rr_title and not has_rr_body:
        return False
    normalized_kind = kind.lower()
    if issue_type:
        return issue_type == normalized_kind
    disposition = disposition_from_body(body)
    if disposition == "CONFIRM" and normalized_kind == "bug":
        return True
    if disposition == "TRACK" and normalized_kind == "task":
        return True
    if disposition in {"CONFIRM", "TRACK"}:
        return False
    return has_rr_title


def sub_issue_nodes(repo: str, number: int) -> list[dict[str, Any]]:
    issue = issue_graph(repo, number)
    nodes: list[dict[str, Any]] = []
    for node in (issue.get("subIssues") or {}).get("nodes") or []:
        nodes.append(
            {
                "repo": node.get("repository", {}).get("nameWithOwner"),
                "number": node.get("number"),
                "title": node.get("title"),
                "url": node.get("url"),
                "state": node.get("state"),
                "body": node.get("body") or "",
                "issue_type": (node.get("issueType") or {}).get("name"),
            }
        )
    return nodes


def list_existing_review_findings(
    sub_issues: list[dict[str, Any]],
    *,
    kind: str,
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for node in sub_issues:
        if not is_rr_sub_issue(node, kind=kind):
            continue
        rr_id = extract_rr_id(node.get("title") or "", node.get("body") or "")
        if rr_id:
            indexed[rr_id] = node
    return indexed


def is_bug_sub_issue(node: dict[str, Any]) -> bool:
    return is_rr_sub_issue(node, kind="bug")


def list_existing_review_bugs(
    sub_issues: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return list_existing_review_findings(sub_issues, kind="bug")


def close_issue(repo: str, number: int, comment: str) -> None:
    ref = issue_ref(repo, number)
    if ref.state == "CLOSED":
        return
    if comment.strip():
        gh_run(
            [
                "issue",
                "comment",
                str(number),
                "--repo",
                repo,
                "--body",
                comment,
            ]
        )
    graphql(CLOSE_ISSUE_MUTATION, {"issueId": ref.node_id})


def sync_one_finding(
    finding: dict[str, Any],
    payload: dict[str, Any],
    parent_ref: IssueRef,
    existing: dict[str, Any] | None,
    *,
    dry_run: bool,
    issue_type: str,
    project_title: str | None,
    kind: str,
) -> dict[str, Any]:
    default_repo = payload["review_issue"]["repo"]
    target_repo = finding.get("repo") or default_repo
    title = finding_title(finding)
    rr_id = finding["id"].upper()

    if existing:
        target_repo = existing.get("repo") or target_repo
        number = int(existing["number"])
        prior_body = existing.get("body")
        if not prior_body:
            try:
                prior_body = _gsp.issue_body(target_repo, number)
            except subprocess.CalledProcessError:
                prior_body = ""
        body = render_finding_body(finding, payload, is_update=True, prior_body=prior_body)
        action = "updated"
        if dry_run:
            result = {
                "id": rr_id,
                "kind": kind,
                "action": action,
                "repo": target_repo,
                "number": number,
                "url": existing.get("url"),
                "title": title,
            }
            requested_id = finding.get("requested_id")
            if requested_id and requested_id.upper() != rr_id:
                result["requested_id"] = requested_id.upper()
            return result
        edit_issue(target_repo, number, title, body)
        ensure_issue_type(target_repo, number, issue_type)
        ref = issue_ref(target_repo, number)
        result = {
            "id": rr_id,
            "kind": kind,
            "action": action,
            "repo": target_repo,
            "number": ref.number,
            "url": ref.url,
            "title": title,
        }
        requested_id = finding.get("requested_id")
        if requested_id and requested_id.upper() != rr_id:
            result["requested_id"] = requested_id.upper()
        return result

    body = render_finding_body(finding, payload, is_update=False)
    action = "created"
    if dry_run:
        result = {
            "id": rr_id,
            "kind": kind,
            "action": action,
            "repo": target_repo,
            "number": None,
            "url": None,
            "title": title,
        }
        requested_id = finding.get("requested_id")
        if requested_id and requested_id.upper() != rr_id:
            result["requested_id"] = requested_id.upper()
        return result

    ref = create_issue(
        target_repo,
        title,
        body,
        labels=[],
        project_title=project_title,
        issue_type=issue_type,
    )
    if sub_issues_supported():
        add_sub_issue(parent_ref.node_id, ref.node_id)
    result = {
        "id": rr_id,
        "kind": kind,
        "action": action,
        "repo": target_repo,
        "number": ref.number,
        "url": ref.url,
        "title": title,
    }
    requested_id = finding.get("requested_id")
    if requested_id and requested_id.upper() != rr_id:
        result["requested_id"] = requested_id.upper()
    return result


def close_stale_finding(
    existing: dict[str, Any],
    *,
    rr_id: str,
    review_date: str,
    triage_path: str,
    reason: str,
    dry_run: bool,
    kind: str,
) -> dict[str, Any]:
    bug_repo = existing["repo"]
    number = int(existing["number"])
    action = "closed"
    comment = (
        f"Re-review on {review_date}: {reason}. "
        f"Triage: `{triage_path}`"
    )
    if dry_run:
        return {
            "id": rr_id,
            "kind": kind,
            "action": action,
            "repo": bug_repo,
            "number": number,
            "url": existing.get("url"),
            "title": existing.get("title"),
        }
    close_issue(bug_repo, number, comment)
    return {
        "id": rr_id,
        "kind": kind,
        "action": action,
        "repo": bug_repo,
        "number": number,
        "url": existing.get("url"),
        "title": existing.get("title"),
    }


def cmd_sync_bugs(args: argparse.Namespace) -> int:
    payload = load_json(args.input)
    review_issue = payload["review_issue"]
    parent_repo = review_issue["repo"]
    parent_number = int(review_issue["number"])
    parent_ref = issue_ref(parent_repo, parent_number)
    bug_issue_type = payload.get("issue_type") or "Bug"
    task_issue_type = payload.get("followup_issue_type") or "Task"
    project = payload.get("project") or {}
    project_title = project.get("title")

    findings = payload.get("findings") or []
    confirm_ids = {
        f["id"].upper()
        for f in findings
        if (f.get("disposition") or "").upper() == "CONFIRM"
    }
    track_ids = {
        f["id"].upper()
        for f in findings
        if (f.get("disposition") or "").upper() == "TRACK"
    }

    all_sub_issues = sub_issue_nodes(parent_repo, parent_number)
    warnings: list[str] = []
    warnings.extend(detect_rr_id_collisions(all_sub_issues))
    warnings.extend(validate_payload_duplicate_rr_ids(findings))
    if sub_issues_missing_issue_types(all_sub_issues):
        warnings.append(
            "Sub-issues lack GitHub issue types; Bug/Task matching falls back to "
            "title prefix and **Disposition:** in issue bodies. Prefer GraphQL "
            "context when sub_issues and issue_types are available."
        )

    existing_bugs = list_existing_review_findings(all_sub_issues, kind="bug")
    existing_tasks = list_existing_review_findings(all_sub_issues, kind="task")

    results: list[dict[str, Any]] = []
    review_date = payload.get("review_date") or utc_today()
    triage_path = payload.get("triage_path") or ""
    used_ids: set[str] = {
        (f.get("id") or "").upper() for f in findings if f.get("id")
    }

    def sync_finding_row(
        finding: dict[str, Any],
        *,
        kind: str,
        issue_type: str,
        existing_pool: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        requested_id = (finding.get("id") or "").upper()
        existing = existing_pool.get(requested_id)
        existing, effective, resolve_warnings, superseded = resolve_existing_for_sync(
            existing,
            finding,
            sub_issues=all_sub_issues,
            used_ids=used_ids,
        )
        warnings.extend(resolve_warnings)
        if effective.get("id", "").upper() != requested_id:
            effective["requested_id"] = requested_id
        result = sync_one_finding(
            effective,
            payload,
            parent_ref,
            existing,
            dry_run=args.dry_run,
            issue_type=issue_type,
            project_title=project_title,
            kind=kind,
        )
        rows = [result]
        if (
            superseded
            and (superseded.get("state") or "").upper() != "CLOSED"
            and result.get("action") == "created"
        ):
            rows.append(
                close_stale_finding(
                    superseded,
                    rr_id=requested_id,
                    review_date=review_date,
                    triage_path=triage_path,
                    reason=(
                        f"superseded by {effective.get('id')} "
                        f"(RR-ID guardrail — different finding)"
                    ),
                    dry_run=args.dry_run,
                    kind=kind,
                )
            )
        return rows

    for finding in findings:
        disposition = (finding.get("disposition") or "").upper()
        rr_id = finding["id"].upper()

        if disposition == "CONFIRM":
            rows = sync_finding_row(
                finding,
                kind="bug",
                issue_type=bug_issue_type,
                existing_pool=existing_bugs,
            )
            results.extend(rows)
            stale_task = existing_tasks.get(rr_id)
            if stale_task and (stale_task.get("state") or "").upper() != "CLOSED":
                results.append(
                    close_stale_finding(
                        stale_task,
                        rr_id=rr_id,
                        review_date=review_date,
                        triage_path=triage_path,
                        reason="re-triaged as CONFIRM bug",
                        dry_run=args.dry_run,
                        kind="task",
                    )
                )
            continue

        if disposition == "TRACK":
            rows = sync_finding_row(
                finding,
                kind="task",
                issue_type=task_issue_type,
                existing_pool=existing_tasks,
            )
            results.extend(rows)
            stale_bug = existing_bugs.get(rr_id)
            if stale_bug and (stale_bug.get("state") or "").upper() != "CLOSED":
                results.append(
                    close_stale_finding(
                        stale_bug,
                        rr_id=rr_id,
                        review_date=review_date,
                        triage_path=triage_path,
                        reason="re-triaged as TRACK task under reviewed issue",
                        dry_run=args.dry_run,
                        kind="bug",
                    )
                )
            continue

    for rr_id, existing in existing_bugs.items():
        if rr_id in confirm_ids:
            continue
        if (existing.get("state") or "").upper() == "CLOSED":
            continue
        dismiss = next(
            (
                f
                for f in findings
                if f.get("id", "").upper() == rr_id
                and (f.get("disposition") or "").upper() == "DISMISS"
            ),
            None,
        )
        if dismiss:
            reason = f"dismissed — {(dismiss.get('dismiss_reason') or 'not confirmed')}"
        elif rr_id in track_ids:
            reason = "re-triaged as TRACK task under reviewed issue"
        else:
            reason = "no longer confirmed on re-review"
        results.append(
            close_stale_finding(
                existing,
                rr_id=rr_id,
                review_date=review_date,
                triage_path=triage_path,
                reason=reason,
                dry_run=args.dry_run,
                kind="bug",
            )
        )

    for rr_id, existing in existing_tasks.items():
        if rr_id in track_ids:
            continue
        if (existing.get("state") or "").upper() == "CLOSED":
            continue
        dismiss = next(
            (
                f
                for f in findings
                if f.get("id", "").upper() == rr_id
                and (f.get("disposition") or "").upper() == "DISMISS"
            ),
            None,
        )
        if dismiss:
            reason = f"dismissed — {(dismiss.get('dismiss_reason') or 'not tracked')}"
        elif rr_id in confirm_ids:
            reason = "re-triaged as CONFIRM bug"
        else:
            reason = "no longer tracked on re-review"
        results.append(
            close_stale_finding(
                existing,
                rr_id=rr_id,
                review_date=review_date,
                triage_path=triage_path,
                reason=reason,
                dry_run=args.dry_run,
                kind="task",
            )
        )

    def count_actions(kind: str, action: str) -> int:
        return sum(
            1
            for row in results
            if row.get("kind") == kind and row.get("action") == action
        )

    summary = {
        "review_issue": review_issue,
        "story_issue": payload.get("story_issue"),
        "dry_run": bool(args.dry_run),
        "warnings": warnings,
        "results": results,
        "counts": {
            "created": sum(1 for r in results if r["action"] == "created"),
            "updated": sum(1 for r in results if r["action"] == "updated"),
            "closed": sum(1 for r in results if r["action"] == "closed"),
            "reallocated": sum(1 for r in results if r.get("requested_id")),
            "bugs": {
                "created": count_actions("bug", "created"),
                "updated": count_actions("bug", "updated"),
                "closed": count_actions("bug", "closed"),
            },
            "tasks": {
                "created": count_actions("task", "created"),
                "updated": count_actions("task", "updated"),
                "closed": count_actions("task", "closed"),
            },
        },
    }
    write_json(args.output, summary)
    return 0


def render_parent_comment(payload: dict[str, Any], sync_summary: dict[str, Any]) -> str:
    findings = payload.get("findings") or []
    confirm = sum(1 for f in findings if (f.get("disposition") or "").upper() == "CONFIRM")
    track = sum(1 for f in findings if (f.get("disposition") or "").upper() == "TRACK")
    dismiss = sum(1 for f in findings if (f.get("disposition") or "").upper() == "DISMISS")
    counts = sync_summary.get("counts") or {}
    bug_counts = counts.get("bugs") or {}
    task_counts = counts.get("tasks") or {}
    story_issue = payload.get("story_issue") or sync_summary.get("story_issue") or {}
    story_line = "_None linked_"
    if story_issue.get("number"):
        story_line = f"#{story_issue.get('number')} — {story_issue.get('url', '')}"

    lines = [
        "## gh-review summary",
        "",
        f"**Review date:** {payload.get('review_date') or utc_today()}",
        f"**Aggregate verdict:** {payload.get('aggregate_verdict', '—')}",
        f"**Triage doc:** `{payload.get('triage_path', '')}`",
        f"**User story (context):** {story_line}",
        "",
        f"**Findings:** {confirm} CONFIRM, {track} TRACK, {dismiss} DISMISS",
        "",
        f"**Bug sync:** {bug_counts.get('created', 0)} created, "
        f"{bug_counts.get('updated', 0)} updated, {bug_counts.get('closed', 0)} closed",
        f"**Task sync:** {task_counts.get('created', 0)} created, "
        f"{task_counts.get('updated', 0)} updated, {task_counts.get('closed', 0)} closed",
        "",
    ]
    sync_warnings = sync_summary.get("warnings") or []
    reallocated = counts.get("reallocated", 0)
    if reallocated:
        lines.append(
            f"**RR-ID guardrails:** {reallocated} finding(s) reallocated to new IDs "
            f"(see warnings — update triage doc to match GitHub)"
        )
        lines.append("")
    if sync_warnings:
        lines.append("### Sync warnings")
        for warning in sync_warnings:
            lines.append(f"- {warning}")
        lines.append("")
    created_bugs = [
        r
        for r in sync_summary.get("results") or []
        if r.get("kind") == "bug" and r["action"] in ("created", "updated")
    ]
    if created_bugs:
        lines.append("### Bug sub-issues (under reviewed issue)")
        for row in created_bugs:
            url = row.get("url") or f"{row.get('repo')}#{row.get('number')}"
            lines.append(f"- [{row.get('id')}] {row.get('title')} — {url}")
        lines.append("")

    created_tasks = [
        r
        for r in sync_summary.get("results") or []
        if r.get("kind") == "task" and r["action"] in ("created", "updated")
    ]
    if created_tasks:
        lines.append("### Task sub-issues (under reviewed issue)")
        for row in created_tasks:
            url = row.get("url") or f"{row.get('repo')}#{row.get('number')}"
            lines.append(f"- [{row.get('id')}] {row.get('title')} — {url}")
    return "\n".join(lines).rstrip() + "\n"


def find_parent_review_comment(repo: str, issue_number: int) -> dict[str, Any] | None:
    try:
        comments = gh_json(
            [
                "api",
                f"repos/{repo}/issues/{issue_number}/comments",
                "--paginate",
            ]
        )
    except subprocess.CalledProcessError:
        return None
    for comment in reversed(comments or []):
        if PARENT_COMMENT_MARKER in (comment.get("body") or ""):
            return comment
    return None


def upsert_parent_review_comment(
    repo: str,
    issue_number: int,
    body: str,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    existing = find_parent_review_comment(repo, issue_number)
    if dry_run:
        return {
            "action": "updated" if existing else "created",
            "comment_id": existing.get("id") if existing else None,
            "body": body,
        }
    if existing:
        comment_id = int(existing["id"])
        gh_run(
            [
                "api",
                "-X",
                "PATCH",
                f"repos/{repo}/issues/comments/{comment_id}",
                "-f",
                f"body={body}",
            ]
        )
        return {"action": "updated", "comment_id": comment_id, "url": existing.get("html_url")}
    gh_run(
        [
            "issue",
            "comment",
            str(issue_number),
            "--repo",
            repo,
            "--body",
            body,
        ]
    )
    created = find_parent_review_comment(repo, issue_number)
    return {
        "action": "created",
        "comment_id": created.get("id") if created else None,
        "url": created.get("html_url") if created else None,
    }


def cmd_comment(args: argparse.Namespace) -> int:
    payload = load_json(args.input)
    sync_summary = load_json(args.sync_summary)
    review_issue = payload["review_issue"]
    body = render_parent_comment(payload, sync_summary)
    if args.dry_run:
        sys.stdout.write(body)
        return 0
    upsert_parent_review_comment(
        review_issue["repo"],
        int(review_issue["number"]),
        body,
        dry_run=False,
    )
    return 0


def cmd_init_payload(args: argparse.Namespace) -> int:
    context = load_json(args.context)
    payload = build_init_payload(context)
    write_json(args.output, payload)
    return 0


def cmd_init_triage_doc(args: argparse.Namespace) -> int:
    context = load_json(args.context)
    triage_path = args.output or suggest_triage_path(context)
    dest = Path(triage_path)
    if dest.exists() and not args.force:
        raise SystemExit(
            f"triage doc already exists: {dest} (use --force to overwrite scaffold)"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_init_triage_doc(context, triage_path), encoding="utf-8")
    result = {"triage_path": triage_path, "written": str(dest.resolve())}
    if args.result_json:
        write_json(args.result_json, result)
    else:
        print(json.dumps(result, indent=2))
    return 0


def cmd_resolve_target(args: argparse.Namespace) -> int:
    context = load_json(args.context)
    target = resolve_review_target(context)
    write_json(args.output, target)
    return 0


def cmd_validate_payload(args: argparse.Namespace) -> int:
    payload = load_json(args.input)
    errors, warnings = validate_payload(payload)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    if warnings and args.strict:
        return 1
    print("payload OK")
    return 0


def cmd_check_consistency(args: argparse.Namespace) -> int:
    payload = load_json(args.input)
    triage_rel = args.triage or payload.get("triage_path")
    if not triage_rel:
        raise SystemExit("--triage required when payload has no triage_path")
    triage_path = Path(triage_rel)
    if not triage_path.is_absolute():
        triage_path = Path.cwd() / triage_path
    errors, warnings = check_payload_triage_consistency(payload, triage_path)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print("payload and triage doc RR-IDs consistent")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    if not args.skip_validate:
        payload = load_json(args.input)
        errors, warnings = validate_payload(payload)
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        if errors:
            for error in errors:
                print(f"error: {error}", file=sys.stderr)
            raise SystemExit("publish aborted — fix payload or use --skip-validate")
    sync_summary = args.output or "/tmp/gh-review-sync.json"
    sync_rc = cmd_sync_bugs(
        argparse.Namespace(
            input=args.input,
            output=sync_summary,
            dry_run=args.dry_run,
        )
    )
    if sync_rc != 0:
        return sync_rc
    return cmd_comment(
        argparse.Namespace(
            input=args.input,
            sync_summary=sync_summary,
            dry_run=args.dry_run,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("preflight", help="Check sub-issue GraphQL support")

    ctx = sub.add_parser("context", help="Gather GitHub issue review context as JSON")
    ctx.add_argument("--issue", required=True, help="URL or OWNER/REPO#N")
    ctx.add_argument("--repo", help="Default repo when --issue is a number")
    ctx.add_argument("--output", "-o", help="Write JSON to path (default stdout)")

    init_payload = sub.add_parser(
        "init-payload",
        help="Scaffold sync-bugs payload from context JSON",
    )
    init_payload.add_argument("--context", required=True, help="context command output JSON")
    init_payload.add_argument("--output", "-o", help="Write payload JSON (default stdout)")

    init_triage = sub.add_parser(
        "init-triage-doc",
        help="Scaffold triage markdown from context JSON and templates",
    )
    init_triage.add_argument("--context", required=True, help="context command output JSON")
    init_triage.add_argument(
        "--output",
        "-o",
        help="Repo-relative triage path (default from context)",
    )
    init_triage.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing triage file",
    )
    init_triage.add_argument(
        "--result-json",
        help="Write {triage_path, written} JSON to path",
    )

    resolve = sub.add_parser(
        "resolve-target",
        help="Pick PR/branch review target from context JSON",
    )
    resolve.add_argument("--context", required=True, help="context command output JSON")
    resolve.add_argument("--output", "-o", help="Write target JSON (default stdout)")

    validate = sub.add_parser(
        "validate-payload",
        help="Validate sync-bugs payload shape and triage rules",
    )
    validate.add_argument("--input", required=True, help="Payload JSON path")
    validate.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on warnings",
    )

    consistency = sub.add_parser(
        "check-consistency",
        help="Compare payload findings[].id with triage markdown RR-IDs",
    )
    consistency.add_argument("--input", required=True, help="Payload JSON path")
    consistency.add_argument(
        "--triage",
        help="Triage markdown path (default: payload triage_path)",
    )

    publish = sub.add_parser(
        "publish",
        help="validate-payload (optional), sync-bugs, then comment",
    )
    publish.add_argument("--input", required=True, help="Payload JSON path")
    publish.add_argument(
        "--output",
        "-o",
        default="/tmp/gh-review-sync.json",
        help="Sync summary JSON path",
    )
    publish.add_argument("--dry-run", action="store_true")
    publish.add_argument(
        "--skip-validate",
        action="store_true",
        help="Skip validate-payload before sync",
    )

    sync = sub.add_parser(
        "sync-bugs",
        help="Create/update/close Bug and Task sub-issues from payload",
    )
    sync.add_argument("--input", required=True, help="JSON payload path")
    sync.add_argument("--output", "-o", help="Write sync summary JSON")
    sync.add_argument("--dry-run", action="store_true")

    comment = sub.add_parser("comment", help="Post summary comment on reviewed issue")
    comment.add_argument("--input", required=True, help="Review payload JSON")
    comment.add_argument("--sync-summary", required=True, help="sync-bugs output JSON")
    comment.add_argument("--dry-run", action="store_true")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "preflight":
        return cmd_preflight(args)
    if args.command == "context":
        return cmd_context(args)
    if args.command == "init-payload":
        return cmd_init_payload(args)
    if args.command == "init-triage-doc":
        return cmd_init_triage_doc(args)
    if args.command == "resolve-target":
        return cmd_resolve_target(args)
    if args.command == "validate-payload":
        return cmd_validate_payload(args)
    if args.command == "check-consistency":
        return cmd_check_consistency(args)
    if args.command == "publish":
        return cmd_publish(args)
    if args.command == "sync-bugs":
        return cmd_sync_bugs(args)
    if args.command == "comment":
        return cmd_comment(args)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
