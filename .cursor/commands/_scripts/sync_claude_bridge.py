#!/usr/bin/env python3
"""Generate .claude/ bridge from .cursor/ harness (skills + translated agents)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CURSOR = REPO_ROOT / ".cursor"
CLAUDE = REPO_ROOT / ".claude"

ADAPTATION = """\
## Cursor → Claude Code

This skill wraps `.cursor/` harness content. Read the entrance file below, then every procedure it links.

- **Subagents:** When a procedure says `Task` with `subagent_type="explore"` (or similar), spawn a Claude Code subagent (`Explore`, `general-purpose`, or a custom agent from `.claude/agents/`).
- **Scripts:** Run helpers under `.cursor/commands/_scripts/` with `python3` from repo root.
- **Paths:** All procedure links resolve relative to the entrance file's directory under `.cursor/commands/`.
"""

ENTRANCES: list[dict[str, object]] = [
    {
        "name": "gh-spec",
        "cursor": "commands/gh/gh-spec.md",
        "description": "Spec-driven development with GitHub parent issue and story sub-issues. Use when user says /gh-spec or wants a GitHub-native spec.",
        "disable_model": True,
    },
    {
        "name": "gh-plan",
        "cursor": "commands/gh/gh-plan.md",
        "description": "GitHub task breakdown from a story issue. Use when user says /gh-plan or wants to plan a GitHub story.",
        "disable_model": True,
    },
    {
        "name": "gh-update-plan",
        "cursor": "commands/gh/gh-update-plan.md",
        "description": "Re-plan after spec or story drift on GitHub branches. Use when user says /gh-update-plan.",
        "disable_model": True,
    },
    {
        "name": "gh-estimate-work",
        "cursor": "commands/gh/gh-estimate-work.md",
        "description": "Bottom-up hour estimates for GitHub issues on the Planning board. Use when user says /gh-estimate-work.",
        "disable_model": True,
    },
    {
        "name": "gh-build",
        "cursor": "commands/gh/gh-build.md",
        "description": "Implement one GitHub task issue with PR and project updates on Composer. Use when user says /gh-build.",
        "disable_model": True,
    },
    {
        "name": "gh-review",
        "cursor": "commands/gh/gh-review.md",
        "description": "GitHub-issue-scoped review with triage and Bug/Task sub-issue sync. Use when user says /gh-review.",
        "disable_model": True,
    },
    {
        "name": "gh-resolve-issues",
        "cursor": "commands/gh/gh-resolve-issues.md",
        "description": "Fix Bug sub-issues from gh-review on the task branch using Composer. Use when user says /gh-resolve-issues.",
        "disable_model": True,
    },
    {
        "name": "plan",
        "cursor": "commands/gh/procedures/lib/plan.md",
        "description": "Local implementation plan without GitHub issues. Use when user says /plan or wants a plan before coding.",
        "disable_model": True,
    },
    {
        "name": "build",
        "cursor": "commands/gh/procedures/lib/build.md",
        "description": "Implement the next task incrementally (local, no GitHub). Use when user says /build.",
        "disable_model": True,
    },
    {
        "name": "aws-sso",
        "cursor": "commands/core/aws-sso.md",
        "description": "Sync AWS SSO profiles for CDK projects. Use when user says /aws-sso or manages AWS profiles.",
        "disable_model": True,
    },
    {
        "name": "find-skills",
        "cursor": "commands/core/find-skills.md",
        "description": "Discover installable agent skills. Use when user says /find-skills or /find-skill.",
        "disable_model": False,
    },
    {
        "name": "caveman",
        "cursor": "commands/core/caveman.md",
        "description": "Ultra-compressed terse output mode. Use when user says /caveman, caveman mode, or wants less tokens.",
        "disable_model": False,
    },
    {
        "name": "commit",
        "cursor": "commands/core/commit.md",
        "description": "Conventional git commit with intelligent staging. Use when user says /commit.",
        "disable_model": True,
        "allowed_tools": "Bash",
    },
    {
        "name": "commit-push",
        "cursor": "commands/core/commit-push.md",
        "description": "Commit then push to remote. Use when user says /commit-push.",
        "disable_model": True,
    },
    {
        "name": "iterate-on-action",
        "cursor": "commands/core/iterate-on-action.md",
        "description": "Commit, push, and fix CI failures. Use when user says /iterate-on-action.",
        "disable_model": True,
    },
    {
        "name": "handoff",
        "cursor": "commands/core/handoff.md",
        "description": "Create or resume session handoff documents. Use when user says /handoff or wants to save context.",
        "disable_model": True,
    },
    {
        "name": "review",
        "cursor": "commands/core/review.md",
        "description": "Five-axis code review for local changes or PRs. Use when user says /review.",
        "disable_model": True,
    },
    {
        "name": "research-issues",
        "cursor": "commands/core/research-issues.md",
        "description": "Triage review findings without GitHub sync. Use when user says /research-issues.",
        "disable_model": True,
    },
    {
        "name": "write-agents-contract",
        "cursor": "commands/core/write-agents-contract.md",
        "description": "Draft or update AGENTS.md contracts, or propose a pitfall for approval. Use when user says /write-agents-contract or an agent discovers a durable gotcha.",
        "disable_model": True,
    },
]


def skill_md(entry: dict[str, object]) -> str:
    name = str(entry["name"])
    cursor_rel = str(entry["cursor"])
    entrance = f".cursor/{cursor_rel}"
    lines = [
        "---",
        f"name: {name}",
        f"description: {entry['description']}",
        "user-invocable: true",
    ]
    if entry.get("disable_model"):
        lines.append("disable-model-invocation: true")
    allowed = entry.get("allowed_tools")
    if allowed:
        lines.append(f"allowed-tools: {allowed}")
    else:
        lines.append("allowed-tools: Read, Bash, Grep, Glob")
    lines.extend(
        [
            "---",
            "",
            ADAPTATION,
            "",
            f"## Entrance",
            "",
            f"Read and follow **`{entrance}`**.",
            "",
        ]
    )
    return "\n".join(lines)


FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
CURSOR_ONLY_KEYS = frozenset({"readonly", "is_background"})


def translate_agent_frontmatter(text: str) -> str:
    """Copy agent body; map Cursor-only frontmatter to Claude Code fields."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return text

    readonly = False
    is_background: bool | None = None
    kept: list[str] = []
    for line in match.group(1).splitlines():
        key = line.split(":", 1)[0].strip()
        if key == "readonly":
            readonly = line.split(":", 1)[1].strip().lower() == "true"
            continue
        if key == "is_background":
            is_background = line.split(":", 1)[1].strip().lower() == "true"
            continue
        if key not in CURSOR_ONLY_KEYS:
            kept.append(line)

    if readonly:
        kept.append("permissionMode: plan")
        kept.append("tools: Read, Grep, Glob, Bash")
    if is_background is not None:
        kept.append(f"background: {'true' if is_background else 'false'}")

    return f"---\n" + "\n".join(kept) + f"\n---\n{text[match.end():]}"


def expected_agent_names() -> set[str]:
    return {
        p.name
        for p in (CURSOR / "agents").glob("*.md")
        if p.name != "index.md"
    }


def expected_skill_names() -> set[str]:
    return {str(entry["name"]) for entry in ENTRANCES}


def prune_stale_agents(agents_dir: Path) -> list[str]:
    removed: list[str] = []
    expected = expected_agent_names()
    for path in agents_dir.glob("*.md"):
        if path.name not in expected:
            path.unlink()
            removed.append(str(path.relative_to(REPO_ROOT)))
    return removed


def prune_stale_skills(skills_root: Path) -> list[str]:
    removed: list[str] = []
    if not skills_root.exists():
        return removed
    expected = expected_skill_names()
    for path in skills_root.iterdir():
        if not path.is_dir():
            continue
        if path.name not in expected:
            shutil.rmtree(path)
            removed.append(str(path.relative_to(REPO_ROOT)))
    return removed


def sync_agents() -> list[str]:
    agents_dir = CLAUDE / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for src in sorted((CURSOR / "agents").glob("*.md")):
        if src.name == "index.md":
            continue
        dest = agents_dir / src.name
        content = translate_agent_frontmatter(src.read_text(encoding="utf-8"))
        if dest.is_symlink():
            dest.unlink()
        existing = dest.read_text(encoding="utf-8") if dest.is_file() else ""
        if existing != content:
            dest.write_text(content, encoding="utf-8")
            written.append(str(dest.relative_to(REPO_ROOT)))
    return written


def sync_skills() -> list[str]:
    skills_root = CLAUDE / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for entry in ENTRANCES:
        name = str(entry["name"])
        skill_dir = skills_root / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        content = skill_md(entry)
        existing = skill_file.read_text(encoding="utf-8") if skill_file.exists() else ""
        if existing != content:
            skill_file.write_text(content, encoding="utf-8")
            created.append(str(skill_file.relative_to(REPO_ROOT)))
    return created


def main() -> int:
    removed_agents = prune_stale_agents(CLAUDE / "agents")
    removed_skills = prune_stale_skills(CLAUDE / "skills")
    agents = sync_agents()
    skills = sync_skills()
    print(f"Agents: {len(agents)} written")
    for path in agents:
        print(f"  {path}")
    if removed_agents:
        print(f"Agents removed: {len(removed_agents)}")
        for path in removed_agents:
            print(f"  {path}")
    print(f"Skills: {len(skills)} written")
    for path in skills:
        print(f"  {path}")
    if removed_skills:
        print(f"Skills removed: {len(removed_skills)}")
        for path in removed_skills:
            print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
