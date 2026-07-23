"""Post an escalation comment on an issue via `gh issue comment`."""

from __future__ import annotations

import subprocess
from typing import Any


def escalate_issue(issue: str, *, reason: str, owner_mention: str = "") -> dict[str, Any]:
    """Comment on `issue` (an `"owner/repo#N"` string) explaining why the
    auto-workflow needs human attention.
    """
    repo, number_str = issue.rsplit("#", 1)
    number = int(number_str)

    lines = ["**Auto-workflow escalation**", reason]
    if owner_mention:
        lines.append(f"cc {owner_mention}")
    body = "\n\n".join(lines)

    subprocess.run(
        ["gh", "issue", "comment", str(number), "--repo", repo, "--body", body],
        check=True,
        capture_output=True,
        text=True,
    )
    return {"issue": issue, "reason": reason, "owner_mention": owner_mention}
