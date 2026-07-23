"""Resolve spawn model from prompt class / job kind (Phase 5).

Default policy:
- ``build`` and ``resolve`` (and resolve-like maintenance) → ``composer-2.5``
- everything else → ``auto``

Config shape (preferred)::

    "spawn": {
      "models": {
        "build": "composer-2.5",
        "resolve": "composer-2.5",
        "default": "auto"
      }
    }

Legacy ``spawn.model`` remains a fallback default when ``models`` is absent.
"""

from __future__ import annotations

from typing import Any

PREMIUM_PROMPT_CLASSES = frozenset(
    {
        "build",
        "resolve",
        "maintenance_deps_bump",
        "maintenance_ruff_rules",
        "maintenance_tier7_anomaly",
    }
)

DEFAULT_PREMIUM_MODEL = "composer-2.5"
DEFAULT_CHEAP_MODEL = "auto"


def _models_map(cfg: dict[str, Any]) -> dict[str, str]:
    spawn = cfg.get("spawn") or {}
    models = spawn.get("models")
    if isinstance(models, dict) and models:
        return {str(k): str(v) for k, v in models.items() if v}
    legacy = spawn.get("model")
    if legacy:
        return {"default": str(legacy), "build": str(legacy), "resolve": str(legacy)}
    return {
        "default": DEFAULT_CHEAP_MODEL,
        "build": DEFAULT_PREMIUM_MODEL,
        "resolve": DEFAULT_PREMIUM_MODEL,
    }


def resolve_model(cfg: dict[str, Any], prompt_class: str | None, *, kind: str | None = None) -> str:
    """Pick the model string for a job.

    Precedence:
    1. Exact ``spawn.models[<prompt_class>]``
    2. Exact ``spawn.models[<kind>]`` when kind differs
    3. ``spawn.models.resolve`` for resolve-like classes
    4. ``spawn.models.build`` for build
    5. Built-in premium/cheap defaults keyed by class
    6. ``spawn.models.default`` / legacy ``spawn.model`` / ``auto``
    """
    models = _models_map(cfg)
    key = prompt_class or kind or ""

    if key and key in models:
        return models[key]
    if kind and kind in models:
        return models[kind]

    if key in PREMIUM_PROMPT_CLASSES or (kind and kind in PREMIUM_PROMPT_CLASSES):
        return models.get("resolve") or models.get("build") or DEFAULT_PREMIUM_MODEL

    return models.get("default") or DEFAULT_CHEAP_MODEL
