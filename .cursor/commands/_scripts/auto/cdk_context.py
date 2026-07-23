"""Read CDK environments from `cdk.json` to derive AWS SSO profile names.

Profile naming matches `.cursor/commands/_scripts/aws/gen_aws_profiles.py`:
``{project_dir_slug}_{env_key}`` (e.g. ``sample_aws_project_staging``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# CDK feature-flag keys in `context` (e.g. "@aws-cdk/aws-lambda:...") are not
# environments. Everything else that is a dict with EnvironmentName/account is.
CDK_FLAG_PREFIX = "@aws-cdk/"


def slug(name: str) -> str:
    """Lowercase snake_case, matching gen_aws_profiles.slug."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_")


def load_cdk_context(repo_root: Path | str) -> dict[str, Any]:
    """Return the ``context`` object from ``repo_root/cdk.json`` (or ``{}``)."""
    path = Path(repo_root) / "cdk.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    context = data.get("context")
    return context if isinstance(context, dict) else {}


def environment_names(context: dict[str, Any]) -> list[str]:
    """Environment keys in ``context`` (dicts carrying EnvironmentName/account).

    Order preserved as declared in cdk.json.
    """
    envs: list[str] = []
    for key, value in context.items():
        if key.startswith(CDK_FLAG_PREFIX):
            continue
        if not isinstance(value, dict):
            continue
        if "EnvironmentName" in value or "account" in value:
            envs.append(key)
    return envs


def project_slug(repo_root: Path | str) -> str:
    """Profile prefix derived from the repo directory name."""
    return slug(Path(repo_root).resolve().name)


def profile_for(repo_root: Path | str, environment: str) -> str:
    """Derive the AWS SSO profile name for ``environment``."""
    return f"{project_slug(repo_root)}_{slug(environment)}"


def environment_profiles(repo_root: Path | str) -> dict[str, str]:
    """Map each cdk.json environment key to its derived profile name."""
    context = load_cdk_context(repo_root)
    prefix = project_slug(repo_root)
    return {env: f"{prefix}_{slug(env)}" for env in environment_names(context)}
