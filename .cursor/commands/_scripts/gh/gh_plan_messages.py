"""Render planning command user messages from _templates/planning/*.md."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_COMMANDS_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATE_DIR = _COMMANDS_DIR / "_templates" / "planning"


def template_path(name: str) -> Path:
    stem = name if name.endswith(".md") else f"{name}.md"
    path = TEMPLATE_DIR / stem
    if not path.is_file():
        raise SystemExit(f"planning template not found: {path}")
    return path


def load_template(name: str) -> str:
    return template_path(name).read_text(encoding="utf-8")


def substitute_placeholders(text: str, values: dict[str, str]) -> str:
    out = text
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    return out


def _format_started_rows(started_branches: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for row in started_branches:
        kind = row.get("kind", "branch")
        branch = row.get("branch", "")
        repo = row.get("repo", "")
        count = row.get("non_merge_count", 0)
        shas = row.get("sample_shas") or []
        if isinstance(shas, str):
            sha_str = shas
        else:
            sha_str = ", ".join(str(s) for s in shas[:3]) if shas else "—"
        rows.append(f"| `{kind}` `{branch}` | {repo} | {count} ({sha_str}) |")
    return "\n".join(rows) if rows else "| — | — | — |"


def render_started_gate_stop(started_branches: list[dict[str, Any]]) -> str:
    template = load_template("started-gate-stop")
    return substitute_placeholders(
        template,
        {"started_rows": _format_started_rows(started_branches)},
    )


def render_branch_started_confirm(started_branches: list[dict[str, Any]]) -> str:
    template = load_template("branch-started-confirm")
    return substitute_placeholders(
        template,
        {"started_rows": _format_started_rows(started_branches)},
    )


def render_rebase_conflict_stop(result: dict[str, Any]) -> str:
    template = load_template("rebase-conflict-stop")
    conflicts = result.get("conflicts") or []
    conflict_list = "\n".join(f"- `{path}`" for path in conflicts) or "- *(unknown)*"
    branch = result.get("story_branch") or result.get("spec_branch") or "branch"
    repo = result.get("home_repo") or ""
    return substitute_placeholders(
        template,
        {
            "branch": branch,
            "repo": repo,
            "conflict_list": conflict_list,
        },
    )


def render_update_plan_outcome(outcome: str, drifted_paths: list[dict[str, Any]] | None = None) -> str:
    if outcome == "unchanged":
        return load_template("update-plan-unchanged").strip()
    if outcome == "synced_valid":
        return load_template("update-plan-synced-valid").strip()
    if outcome == "drift":
        template = load_template("update-plan-drift")
        lines = []
        for item in drifted_paths or []:
            repo = item.get("repo", "")
            path = item.get("path", "")
            lines.append(f"- `{path}` ({repo})")
        drift_list = "\n".join(lines) if lines else "- *(none listed)*"
        return substitute_placeholders(template, {"drift_list": drift_list}).strip()
    raise SystemExit(f"unknown update-plan outcome: {outcome!r}")


def attach_sync_user_message(result: dict[str, Any]) -> dict[str, Any]:
    reason = result.get("blocked_reason")
    if reason == "implementation_in_progress":
        result["user_message"] = render_started_gate_stop(result.get("started_branches") or [])
    elif reason == "branch_started":
        result["user_message"] = render_branch_started_confirm(result.get("started_branches") or [])
    elif reason == "rebase_conflict":
        result["user_message"] = render_rebase_conflict_stop(result)
    else:
        result.setdefault("user_message", None)
    return result


def render_message(template: str, payload: dict[str, Any]) -> str:
    name = template.removesuffix(".md")
    if name == "started-gate-stop":
        return render_started_gate_stop(payload.get("started_branches") or [])
    if name == "branch-started-confirm":
        return render_branch_started_confirm(payload.get("started_branches") or [])
    if name == "rebase-conflict-stop":
        return render_rebase_conflict_stop(payload)
    if name in ("update-plan-unchanged", "unchanged"):
        return render_update_plan_outcome("unchanged")
    if name in ("update-plan-synced-valid", "synced_valid"):
        return render_update_plan_outcome("synced_valid")
    if name in ("update-plan-drift", "drift"):
        return render_update_plan_outcome("drift", payload.get("drifted_paths"))
    raise SystemExit(f"unsupported render-message template: {template!r}")
