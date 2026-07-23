"""Declarative Phase 5 domain pack registry.

Packs mirror Phase 4 maintenance: probe → claim → admitted spawn.
Pack definitions live under ``packs/*.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from memory import MemoryStore, fingerprint
from registry import Registry

_PACKS_DIR = Path(__file__).resolve().parent / "packs"

PACK_NAMES = frozenset(
    {
        "cdk_migration",
        "iam_security_sweep",
        "feedback_remediation",
        "cost_regression",
    }
)


def packs_dir() -> Path:
    return _PACKS_DIR


def load_pack(name: str, *, directory: Path | None = None) -> dict[str, Any]:
    if name not in PACK_NAMES:
        raise ValueError(f"unknown domain pack: {name!r}")
    path = (directory or _PACKS_DIR) / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"pack {name} root must be an object")
    data.setdefault("name", name)
    data.setdefault("prompt_class", f"domain_{name}")
    data.setdefault("marker", f"auto-workflow:domain:{name}")
    return data


def list_packs(*, directory: Path | None = None) -> list[str]:
    root = directory or _PACKS_DIR
    if not root.is_dir():
        return sorted(PACK_NAMES)
    found = [p.stem for p in root.glob("*.json") if p.stem in PACK_NAMES]
    return sorted(found or PACK_NAMES)


def default_probe(pack: dict[str, Any], *, repo: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Conservative probe: always spawn unless pack says noop."""
    name = pack["name"]
    marker = pack.get("marker") or f"auto-workflow:domain:{name}"
    return {
        "action": "spawn",
        "reason": pack.get("description") or f"run domain pack {name}",
        "duplicate": False,
        "inputs": {"pack": name, "repo": repo, "marker": marker},
        "context": {
            "marker": marker,
            "pack": name,
            "repo": repo,
            "instructions": pack.get("instructions") or "",
            "mcp_required": bool(pack.get("mcp_required")),
        },
    }


def probe_cost_regression(pack: dict[str, Any], *, repo: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Require explicit MCP config; otherwise setup_alert (not silent success)."""
    spawn = cfg.get("spawn") or {}
    mcp = spawn.get("mcp") or cfg.get("mcp") or {}
    pricing_ok = bool(mcp.get("aws_pricing") or mcp.get("plugin-deploy-on-aws-awspricing"))
    marker = pack.get("marker") or "auto-workflow:domain:cost_regression"
    if not pricing_ok:
        return {
            "action": "setup_alert",
            "reason": "AWS pricing MCP not configured for spawn",
            "duplicate": False,
            "inputs": {"pack": "cost_regression", "mcp": "missing"},
            "context": {
                "marker": marker,
                "pack": "cost_regression",
                "repo": repo,
                "details": "Set spawn.mcp.aws_pricing=true (or install pricing MCP) before cost_regression runs.",
            },
        }
    return default_probe(pack, repo=repo, cfg=cfg)


PROBES: dict[str, Callable[..., dict[str, Any]]] = {
    "cost_regression": probe_cost_regression,
}


def run_pack_probe(
    name: str,
    cfg: dict[str, Any],
    *,
    pack_dir: Path | None = None,
    probe_override: Callable[..., dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    pack = load_pack(name, directory=pack_dir)
    if probe_override is not None:
        probe = probe_override()
    else:
        probe_fn = PROBES.get(name, default_probe)
        probe = probe_fn(pack, repo=cfg["repo"], cfg=cfg)
    return pack, probe


def run_pack(
    name: str,
    cfg: dict[str, Any],
    *,
    pack_dir: Path | None = None,
    spawn_headless_fn=None,
    spawn_worker_fn=None,
    probe_override: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Probe + claim + admit spawn for a domain pack."""
    from pathlib import Path as _Path

    from admission import admit_and_spawn
    from config import resolve_path
    from intent_queue import IntentQueue
    from log import RunLog

    root = _Path(cfg["_repo_root"])
    state_dir = resolve_path(root, cfg["state_dir"])
    log_dir = resolve_path(root, cfg["log_dir"])
    workspace = resolve_path(root, cfg.get("workspace") or ".")
    memory = MemoryStore(state_dir)
    registry = Registry(state_dir)
    run_log = RunLog(log_dir)

    pack, probe = run_pack_probe(
        name, cfg, pack_dir=pack_dir, probe_override=probe_override
    )
    fp = fingerprint(f"domain:{name}", probe["inputs"], pack.get("policy_version", 1))
    ttl = int((cfg.get("maintenance") or {}).get("claim_ttl_seconds") or 21600)
    claim = memory.claim(f"domain:{name}", fp, ttl_seconds=ttl)
    if claim == "known_good":
        return {"pack": name, "status": "skipped_known_good", "fingerprint": fp}
    if claim == "busy":
        return {"pack": name, "status": "skipped_busy", "fingerprint": fp}

    action = probe.get("action")
    if action == "noop" or probe.get("duplicate"):
        memory.complete(f"domain:{name}", fp, metadata={"reason": probe.get("reason")})
        return {"pack": name, "status": "noop", "fingerprint": fp, "probe": probe}

    ctx = probe.get("context") or {}
    prompt_class = pack.get("prompt_class") or f"domain_{name}"
    transition = {
        "issue": f"domain:{name}:{fp[:12]}",
        "repo": cfg["repo"],
        "url": "",
        "title": f"domain pack {name}",
        "marker": ctx.get("marker") or pack.get("marker"),
        "pack_name": name,
        "pack": name,
        "instructions": ctx.get("instructions") or pack.get("instructions") or "",
        "reason": probe.get("reason", ""),
        "details_json": json.dumps(ctx, sort_keys=True, default=str),
    }
    result = admit_and_spawn(
        cfg=cfg,
        registry=registry,
        run_log=run_log,
        workspace=workspace,
        log_dir=log_dir,
        kind=f"domain_{name}",
        prompt_class=prompt_class,
        transition=transition,
        lock_key=f"domain:{name}",
        intent_queue=IntentQueue(state_dir),
        job_extras={
            "fingerprint": fp,
            "domain_pack": name,
            "target": name,
        },
        spawn_headless_fn=spawn_headless_fn,
        spawn_worker_fn=spawn_worker_fn,
    )
    if result["status"] == "spawned":
        return {
            "pack": name,
            "status": "spawned",
            "fingerprint": fp,
            "job_record": result["job"],
            "probe": probe,
        }
    if result["status"] == "queued":
        return {
            "pack": name,
            "status": "queued",
            "fingerprint": fp,
            "intent": result.get("intent"),
            "probe": probe,
        }
    if result["status"] == "spawn_error":
        memory.fail(f"domain:{name}", fp, error=result.get("reason") or "spawn_error")
        return {
            "pack": name,
            "status": "spawn_error",
            "error": result.get("reason"),
            "probe": probe,
        }
    memory.release_claim(f"domain:{name}", fp)
    return {
        "pack": name,
        "status": result.get("status") or "skipped",
        "reason": result.get("reason"),
        "probe": probe,
    }
