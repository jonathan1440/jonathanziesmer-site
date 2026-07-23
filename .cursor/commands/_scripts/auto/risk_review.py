"""Risk classification and SHA-bound contract SIGN-OFF gate (Phase 5)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Paths / keywords that map to AGENTS.md "needs a design conversation first".
DESIGN_CONVERSATION_PATTERNS = (
    re.compile(r"\.github/workflows/", re.I),
    re.compile(r"\.github/actions/deploy-cdk", re.I),
    re.compile(r"cdk_params_for_env\.py$", re.I),
    re.compile(r"infrastructure/.+stack", re.I),
)

DESIGN_CONVERSATION_KEYWORDS = (
    "new deployment environment",
    "multiple cdk stacks",
    "replacing oidc",
    "param injection",
    "cdk-out artifact",
)

NORMAL_SHIPPABLE_HINTS = (
    "requirements",
    "ruff",
    "tests/",
    "docs/",
    "scripts/github-setup",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_change(
    *,
    paths: list[str] | None = None,
    summary: str = "",
    agents_md: str = "",
) -> dict[str, Any]:
    """Map a PR to ``normal`` or ``design_conversation``.

    Uncertain / matching design patterns → ``design_conversation``.
    """
    paths = paths or []
    evidence: list[str] = []
    refs: list[str] = []
    summary_l = summary.lower()

    for pattern in DESIGN_CONVERSATION_PATTERNS:
        for path in paths:
            if pattern.search(path):
                evidence.append(f"path matches design pattern: {path}")
                refs.append("AGENTS.md#Needs a design conversation first")

    for keyword in DESIGN_CONVERSATION_KEYWORDS:
        if keyword in summary_l or keyword in agents_md.lower():
            # Only treat keyword hits in the change summary as evidence.
            if keyword in summary_l:
                evidence.append(f"summary mentions {keyword!r}")
                refs.append("AGENTS.md#Needs a design conversation first")

    # Splitting stacks / new env heuristics from path sets
    if any("infrastructure/" in p and "stack" in p.lower() for p in paths):
        if len([p for p in paths if "infrastructure/" in p]) >= 3:
            evidence.append("large infrastructure surface area")
            refs.append("AGENTS.md#Needs a design conversation first")

    if evidence:
        return {
            "category": "design_conversation",
            "evidence": evidence,
            "agents_md_refs": sorted(set(refs)),
            "classified_at": _now_iso(),
        }

    # Default normal when only shippable-looking paths, else design (conservative).
    if paths and all(
        any(h in p for h in NORMAL_SHIPPABLE_HINTS) or p.endswith(".md") for p in paths
    ):
        return {
            "category": "normal",
            "evidence": ["paths match shippable-after-normal-PR-review patterns"],
            "agents_md_refs": ["AGENTS.md#Shippable after normal PR review"],
            "classified_at": _now_iso(),
        }

    if not paths and not summary.strip():
        return {
            "category": "design_conversation",
            "evidence": ["no paths or summary provided; uncertain"],
            "agents_md_refs": ["AGENTS.md#Needs a design conversation first"],
            "classified_at": _now_iso(),
        }

    return {
        "category": "normal",
        "evidence": ["no design-conversation signals detected"],
        "agents_md_refs": ["AGENTS.md#Shippable after normal PR review"],
        "classified_at": _now_iso(),
    }


def extract_contract_signoff(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Read machine-checkable SIGN-OFF block from a review publish payload."""
    block = payload.get("contract_signoff")
    if isinstance(block, dict) and block.get("verdict"):
        return block
    # Nested under meta / gate
    for key in ("meta", "gate", "contract"):
        nested = payload.get(key)
        if isinstance(nested, dict) and isinstance(nested.get("contract_signoff"), dict):
            return nested["contract_signoff"]
    return None


def signoff_valid(
    payload: dict[str, Any],
    *,
    head_sha: str,
) -> dict[str, Any]:
    """Require SIGN-OFF bound to the current PR head SHA."""
    block = extract_contract_signoff(payload)
    if not block:
        return {"ok": False, "reason": "missing_contract_signoff"}
    verdict = str(block.get("verdict") or "").upper()
    if verdict != "SIGN-OFF":
        return {"ok": False, "reason": f"verdict_{verdict or 'empty'}", "block": block}
    signed_sha = str(block.get("head_sha") or "")
    if not head_sha:
        return {"ok": False, "reason": "missing_current_head_sha", "block": block}
    if signed_sha != head_sha:
        return {
            "ok": False,
            "reason": "head_sha_mismatch",
            "signed_sha": signed_sha,
            "head_sha": head_sha,
            "block": block,
        }
    return {"ok": True, "block": block}


def risk_gate(
    *,
    risk: dict[str, Any],
    review_payload: dict[str, Any] | None,
    head_sha: str,
) -> dict[str, Any]:
    """Combined gate before requesting human review / Ready to ship."""
    category = (risk or {}).get("category") or "design_conversation"
    if category == "design_conversation":
        return {
            "ok": False,
            "action": "latch",
            "reason": "design_conversation",
            "risk": risk,
        }
    if review_payload is None:
        return {"ok": False, "action": "wait", "reason": "missing_review_payload"}
    check = signoff_valid(review_payload, head_sha=head_sha)
    if not check["ok"]:
        return {
            "ok": False,
            "action": "block",
            "reason": check["reason"],
            "signoff": check,
            "risk": risk,
        }
    return {"ok": True, "action": "request_human_review", "risk": risk, "signoff": check}


def apply_risk_to_registry(registry, issue: str, risk: dict[str, Any]) -> None:
    """Latch or clear design-conversation hard-stop on an issue."""
    if risk.get("category") == "design_conversation":
        registry.mark_risk_latched(issue)
    else:
        registry.clear_risk_latched(issue)


def load_json(path: Path | str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data
