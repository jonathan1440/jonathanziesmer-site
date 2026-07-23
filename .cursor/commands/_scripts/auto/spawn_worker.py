"""Spawn a Cursor Cloud Agent ("worker") run via the Cursor API for a dispatched job."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class WorkerSpawnError(RuntimeError):
    """Raised when the Cursor API rejects or fails a worker-mode agent launch."""


def spawn_worker(
    *,
    prompt: str,
    model: str | None,
    worker_type: str,
    worker_name: str,
    repo_url: str,
    api_base: str = "https://api.cursor.com",
) -> dict[str, Any]:
    """Launch a cloud/worker agent via the Cursor API. No local pid to track."""
    if not worker_name:
        raise WorkerSpawnError("worker_name is required for worker-mode spawn")

    api_key = os.environ.get("CURSOR_API_KEY")
    if not api_key:
        raise WorkerSpawnError("CURSOR_API_KEY is not set; cannot spawn a worker agent")

    payload = json.dumps(
        {
            "prompt": {"text": prompt},
            "model": model,
            "source": {"repository": repo_url},
            "target": {"type": worker_type, "name": worker_name},
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        f"{api_base}/v0/agents",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise WorkerSpawnError(f"failed to spawn worker agent: {exc}") from exc

    request_id = body.get("id") or body.get("request_id")
    if not request_id:
        raise WorkerSpawnError(f"worker spawn response missing agent id: {body}")

    return {
        "mode": "worker",
        "pid": None,
        "chat_id": body.get("chat_id"),
        "request_id": request_id,
    }
