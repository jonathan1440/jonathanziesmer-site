"""Shared parsers for gh-plan task issue bodies and scope tables."""

from __future__ import annotations

import re


def section_text(body: str, heading: str) -> str:
    pattern = re.compile(rf"^{re.escape(heading)}\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(body)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^##\s+", body[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(body)
    return body[start:end].strip()


def parse_scope_files(body: str) -> list[str]:
    """Parse ## Scope table paths; raise SystemExit when section or rows missing."""
    files = parse_scope_files_optional(body)
    if not files:
        raise SystemExit("task issue missing ## Scope file table")
    return files


def parse_scope_files_optional(body: str) -> list[str]:
    """Parse ## Scope table paths; return [] when section is absent or empty."""
    text = section_text(body, "## Scope")
    if not text:
        return []
    files: list[str] = []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        if re.match(r"^\|\s*-+", line):
            continue
        if "file" in line.lower() and "change" in line.lower():
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        path = cells[0].strip("` ")
        if path and path.lower() != "file" and not path.startswith("-"):
            files.append(path)
    return files
