"""Load and validate `.cursor/auto-workflow.json`.

Phase 1-2 fields: project, repo, poll_interval_seconds, concurrency,
retry_budget, spawn, workspace, state_dir, log_dir, escalate_owner.

Phase 3 adds: chain_failure_budget, merged_pr_lookback_hours.

Phase 4 adds: maintenance (timers, memory TTL, stale threshold, AWS profile,
usage summary). Host-specific overrides live in gitignored
``.cursor/auto-workflow.local.json`` (deep-merged over the base config).

Phase 5 adds: ``spawn.models`` per job class (build/resolve premium; default
cheap). Daily quotas are intentionally not implemented.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import cdk_context

CONFIG_RELATIVE_PATH = ".cursor/auto-workflow.json"
LOCAL_CONFIG_RELATIVE_PATH = ".cursor/auto-workflow.local.json"

DEFAULT_CHAIN_FAILURE_BUDGET = 3
DEFAULT_MERGED_PR_LOOKBACK_HOURS = 72

DEFAULT_MAINTENANCE: dict[str, Any] = {
    "enabled": True,
    "claim_ttl_seconds": 21600,
    # tier7 targets this cdk.json environment; the AWS SSO profile is derived
    # from cdk.json + the repo name unless `aws_profile` is set explicitly.
    "aws_environment": "staging",
    "aws_profile": "",
    "stale_days": 30,
    "jobs": {
        "deps_bump": {
            "enabled": True,
            "interval_hours": 168,
            "policy_version": 1,
        },
        "ruff_rules": {
            "enabled": True,
            "interval_hours": 720,
            "policy_version": 1,
        },
        "docs_drift": {
            "enabled": True,
            "interval_hours": 168,
            "policy_version": 1,
        },
        "stale_triage": {
            "enabled": True,
            "interval_hours": 168,
            "policy_version": 1,
        },
        "tier7_staging": {
            "enabled": True,
            "interval_hours": 24,
            "policy_version": 1,
        },
    },
    "summary": {
        "enabled": True,
        "hour_utc": 6,
    },
}

MAINTENANCE_JOB_NAMES = frozenset(DEFAULT_MAINTENANCE["jobs"])

VALID_SPAWN_MODES = frozenset({"headless", "worker"})

DEFAULT_SPAWN_MODELS: dict[str, str] = {
    "build": "composer-2.5",
    "resolve": "composer-2.5",
    "default": "auto",
}


class ConfigError(ValueError):
    """Raised when `.cursor/auto-workflow.json` is missing or invalid."""


def resolve_path(repo_root: Path | str, relative: str | Path) -> Path:
    """Resolve a config-relative path against the repo root."""
    root = Path(repo_root)
    rel = Path(relative)
    if rel.is_absolute():
        return rel
    return (root / rel).resolve()


def ensure_dir(path: Path | str) -> Path:
    """Create `path` (and parents) if missing, and return it as a `Path`."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` into a copy of ``base``.

    Dict values merge; all other types (including lists) replace.
    """
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config root must be an object: {path}")
    return raw


def _apply_maintenance_defaults(cfg: dict[str, Any]) -> None:
    maintenance = deep_merge(DEFAULT_MAINTENANCE, cfg.get("maintenance") or {})
    cfg["maintenance"] = maintenance


def _apply_spawn_model_defaults(cfg: dict[str, Any]) -> None:
    """Normalize ``spawn.models``; keep legacy ``spawn.model`` as fallback default."""
    spawn = cfg.get("spawn")
    if not isinstance(spawn, dict):
        return
    models = spawn.get("models")
    if not isinstance(models, dict) or not models:
        legacy = spawn.get("model")
        if legacy:
            spawn["models"] = {
                "default": str(legacy),
                "build": str(legacy),
                "resolve": str(legacy),
            }
        else:
            spawn["models"] = dict(DEFAULT_SPAWN_MODELS)
    else:
        spawn["models"] = deep_merge(DEFAULT_SPAWN_MODELS, models)
    # Keep spawn.model as the resolved default for older call sites.
    spawn["model"] = spawn["models"].get("default") or DEFAULT_SPAWN_MODELS["default"]


def load_config(repo_root: Path | str) -> dict[str, Any]:
    """Read, validate, and normalize `.cursor/auto-workflow.json`.

    Returns a config dict with `workspace`, `state_dir`, and `log_dir`
    resolved to absolute path strings, and Phase 3/4 defaults filled in.
    If `.cursor/auto-workflow.local.json` exists it is deep-merged on top.
    """
    root = Path(repo_root)
    config_path = root / CONFIG_RELATIVE_PATH
    if not config_path.is_file():
        raise ConfigError(f"missing config file: {config_path}")

    cfg = _read_json_file(config_path)

    local_path = root / LOCAL_CONFIG_RELATIVE_PATH
    if local_path.is_file():
        cfg = deep_merge(cfg, _read_json_file(local_path))

    cfg.setdefault("chain_failure_budget", DEFAULT_CHAIN_FAILURE_BUDGET)
    cfg.setdefault("merged_pr_lookback_hours", DEFAULT_MERGED_PR_LOOKBACK_HOURS)
    _apply_maintenance_defaults(cfg)
    _apply_spawn_model_defaults(cfg)

    validate_config(cfg)

    cfg["_repo_root"] = str(root)
    cfg["workspace"] = str(resolve_path(root, cfg["workspace"]))
    cfg["state_dir"] = str(resolve_path(root, cfg["state_dir"]))
    cfg["log_dir"] = str(resolve_path(root, cfg["log_dir"]))
    _resolve_aws_profile(cfg["maintenance"], root)
    return cfg


def _resolve_aws_profile(maintenance: dict[str, Any], repo_root: Path) -> None:
    """Fill `maintenance.aws_profile` from cdk.json when not set explicitly.

    Also records the discovered cdk.json environments + their derived profile
    names under `maintenance.cdk_environments` / `maintenance.cdk_profiles`.
    An explicit non-empty `aws_profile` always wins.
    """
    environments = cdk_context.environment_names(cdk_context.load_cdk_context(repo_root))
    profiles = cdk_context.environment_profiles(repo_root)
    maintenance["cdk_environments"] = environments
    maintenance["cdk_profiles"] = profiles

    explicit = maintenance.get("aws_profile")
    if explicit:
        return

    environment = maintenance.get("aws_environment") or "staging"
    if environments and environment not in environments:
        raise ConfigError(
            f"maintenance.aws_environment {environment!r} is not defined in "
            f"cdk.json context; available environments: {environments}"
        )
    maintenance["aws_profile"] = cdk_context.profile_for(repo_root, environment)


def validate_config(cfg: dict[str, Any]) -> None:
    """Raise ConfigError if required fields are missing or malformed."""
    required_top_level = (
        "project",
        "repo",
        "poll_interval_seconds",
        "concurrency",
        "retry_budget",
        "spawn",
        "workspace",
        "state_dir",
        "log_dir",
    )
    for field in required_top_level:
        if field not in cfg:
            raise ConfigError(f"missing required config field: {field}")

    project = cfg["project"]
    if not isinstance(project, dict) or "owner" not in project or "number" not in project:
        raise ConfigError("project must be an object with 'owner' and 'number'")

    if not isinstance(cfg["repo"], str) or "/" not in cfg["repo"]:
        raise ConfigError("repo must be 'owner/name'")

    if not isinstance(cfg["poll_interval_seconds"], (int, float)) or cfg["poll_interval_seconds"] <= 0:
        raise ConfigError("poll_interval_seconds must be a positive number")

    if not isinstance(cfg["concurrency"], int) or cfg["concurrency"] < 1:
        raise ConfigError("concurrency must be a positive integer")

    if not isinstance(cfg["retry_budget"], int) or cfg["retry_budget"] < 0:
        raise ConfigError("retry_budget must be a non-negative integer")

    spawn = cfg["spawn"]
    if not isinstance(spawn, dict):
        raise ConfigError("spawn must be an object")
    mode = spawn.get("mode")
    if mode not in VALID_SPAWN_MODES:
        raise ConfigError(f"spawn.mode must be one of {sorted(VALID_SPAWN_MODES)}, got {mode!r}")
    if mode == "worker":
        worker = spawn.get("worker") or {}
        if not isinstance(worker, dict) or not worker.get("name"):
            raise ConfigError("spawn.worker.name is required when spawn.mode is 'worker'")
    if "models" in spawn:
        models = spawn["models"]
        if not isinstance(models, dict):
            raise ConfigError("spawn.models must be an object")
        for key, value in models.items():
            if not isinstance(key, str) or not key:
                raise ConfigError("spawn.models keys must be non-empty strings")
            if not isinstance(value, str) or not value:
                raise ConfigError(f"spawn.models.{key} must be a non-empty string")

    if "chain_failure_budget" in cfg:
        budget = cfg["chain_failure_budget"]
        if not isinstance(budget, int) or budget < 1:
            raise ConfigError("chain_failure_budget must be a positive integer")

    if "merged_pr_lookback_hours" in cfg:
        lookback = cfg["merged_pr_lookback_hours"]
        if not isinstance(lookback, (int, float)) or lookback <= 0:
            raise ConfigError("merged_pr_lookback_hours must be a positive number")

    if "maintenance" in cfg:
        _validate_maintenance(cfg["maintenance"])


def _validate_maintenance(maintenance: Any) -> None:
    if not isinstance(maintenance, dict):
        raise ConfigError("maintenance must be an object")

    if "enabled" in maintenance and not isinstance(maintenance["enabled"], bool):
        raise ConfigError("maintenance.enabled must be a boolean")

    if "claim_ttl_seconds" in maintenance:
        ttl = maintenance["claim_ttl_seconds"]
        if not isinstance(ttl, int) or ttl < 1:
            raise ConfigError("maintenance.claim_ttl_seconds must be a positive integer")

    if "stale_days" in maintenance:
        days = maintenance["stale_days"]
        if not isinstance(days, (int, float)) or days <= 0:
            raise ConfigError("maintenance.stale_days must be a positive number")

    if "aws_profile" in maintenance and not isinstance(maintenance["aws_profile"], str):
        raise ConfigError("maintenance.aws_profile must be a string")

    if "aws_environment" in maintenance and not isinstance(maintenance["aws_environment"], str):
        raise ConfigError("maintenance.aws_environment must be a string")

    jobs = maintenance.get("jobs")
    if jobs is not None:
        if not isinstance(jobs, dict):
            raise ConfigError("maintenance.jobs must be an object")
        for name, job in jobs.items():
            if name not in MAINTENANCE_JOB_NAMES:
                raise ConfigError(
                    f"unknown maintenance job {name!r}; "
                    f"expected one of {sorted(MAINTENANCE_JOB_NAMES)}"
                )
            if not isinstance(job, dict):
                raise ConfigError(f"maintenance.jobs.{name} must be an object")
            if "enabled" in job and not isinstance(job["enabled"], bool):
                raise ConfigError(f"maintenance.jobs.{name}.enabled must be a boolean")
            if "interval_hours" in job:
                hours = job["interval_hours"]
                if not isinstance(hours, (int, float)) or hours <= 0:
                    raise ConfigError(
                        f"maintenance.jobs.{name}.interval_hours must be a positive number"
                    )
            if "policy_version" in job:
                ver = job["policy_version"]
                if not isinstance(ver, (int, str)) or ver == "":
                    raise ConfigError(
                        f"maintenance.jobs.{name}.policy_version must be int or non-empty str"
                    )

    summary = maintenance.get("summary")
    if summary is not None:
        if not isinstance(summary, dict):
            raise ConfigError("maintenance.summary must be an object")
        if "enabled" in summary and not isinstance(summary["enabled"], bool):
            raise ConfigError("maintenance.summary.enabled must be a boolean")
        if "hour_utc" in summary:
            hour = summary["hour_utc"]
            if not isinstance(hour, int) or not 0 <= hour <= 23:
                raise ConfigError("maintenance.summary.hour_utc must be an int 0-23")
