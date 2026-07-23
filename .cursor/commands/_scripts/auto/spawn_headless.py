"""Spawn a detached `cursor-agent` headless CLI process for a dispatched job."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import Any


def spawn_headless(
    *,
    prompt: str,
    workspace: str,
    model: str | None = None,
    log_path: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Launch `cursor-agent -p -f` in the background, logging to `log_path`.

    Returns immediately with the child pid; does not wait for completion.
    """
    request_id = uuid.uuid4().hex

    cmd = [
        "cursor-agent",
        "-p",
        "-f",
        "--approve-mcps",
        "--workspace",
        workspace,
        "--output-format",
        "json",
    ]
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)

    popen_kwargs: dict[str, Any] = {"stderr": subprocess.STDOUT, "start_new_session": True}
    if env is not None:
        popen_kwargs["env"] = env

    log_file = None
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "a")
        popen_kwargs["stdout"] = log_file
    else:
        popen_kwargs["stdout"] = subprocess.DEVNULL

    try:
        process = subprocess.Popen(cmd, **popen_kwargs)
    finally:
        if log_file is not None:
            log_file.close()

    return {
        "mode": "headless",
        "pid": process.pid,
        "request_id": request_id,
        "chat_id": None,
    }
