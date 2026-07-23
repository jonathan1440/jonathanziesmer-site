"""Nightly usage summary from dispatcher NDJSON logs.

Usage:
  python3 usage_summary.py [--repo-root PATH] [--date YYYY-MM-DD]

Writes ``log_dir/summaries/YYYY-MM-DD.json`` and prints a concise text report.
Does not create GitHub issues. Admin API enrichment is intentionally absent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from config import ensure_dir, load_config, resolve_path
from log import SCHEMA_VERSION, RunLog


def _repo_root_from_script() -> Path:
    return _SCRIPT_DIR.parents[3]


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True, default=str)
            f.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def aggregate_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate lifecycle + legacy events into a usage summary dict."""
    started = 0
    finished = 0
    failures = 0
    timeouts = 0
    unknown_outcomes = 0
    malformed_or_skipped = 0
    durations: list[float] = []
    by_prompt_class: Counter[str] = Counter()
    by_mode: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    run_ids_started: set[str] = set()
    run_ids_finished: set[str] = set()

    for record in records:
        if not isinstance(record, dict):
            malformed_or_skipped += 1
            continue
        schema = record.get("schema_version")
        if schema is not None and schema != SCHEMA_VERSION:
            # Future/unknown schema — count but do not crash.
            malformed_or_skipped += 1
            continue

        event = record.get("event")
        if event == "run_started":
            started += 1
            run_id = record.get("run_id")
            if run_id:
                run_ids_started.add(str(run_id))
            prompt_class = record.get("prompt_class") or "unknown"
            mode = record.get("mode") or "unknown"
            kind = record.get("kind") or "unknown"
            by_prompt_class[prompt_class] += 1
            by_mode[mode] += 1
            by_kind[kind] += 1
            continue

        if event == "run_finished":
            finished += 1
            run_id = record.get("run_id")
            if run_id:
                run_ids_finished.add(str(run_id))
            status = record.get("status")
            if status in ("failed", "error"):
                failures += 1
            if status == "timeout":
                timeouts += 1
            if record.get("outcome_known") is False:
                unknown_outcomes += 1
            dur = record.get("duration_seconds")
            if isinstance(dur, (int, float)):
                durations.append(float(dur))
            continue

        # Legacy pre-schema events — ignore for primary counters; lifecycle
        # run_started/run_finished are authoritative once Phase 4 is live.
        if event in ("spawn", "retry_spawn", "maintenance_spawn", "reap", "reap_failed", "escalated"):
            continue
        if event == "spawn_error":
            failures += 1
            continue

    unfinished = len(run_ids_started - run_ids_finished)
    total_duration = sum(durations)
    avg_duration = (total_duration / len(durations)) if durations else None

    return {
        "schema_version": SCHEMA_VERSION,
        "runs_started": started,
        "runs_finished": finished,
        "failures": failures,
        "timeouts": timeouts,
        "unknown_outcomes": unknown_outcomes,
        "unfinished": unfinished,
        "duration_known_count": len(durations),
        "duration_total_seconds": round(total_duration, 3),
        "duration_average_seconds": None if avg_duration is None else round(avg_duration, 3),
        "by_prompt_class": dict(sorted(by_prompt_class.items())),
        "by_mode": dict(sorted(by_mode.items())),
        "by_kind": dict(sorted(by_kind.items())),
        "malformed_or_skipped": malformed_or_skipped,
    }


def build_summary_for_day(log: RunLog, day: date | str) -> dict[str, Any]:
    if isinstance(day, str):
        day = date.fromisoformat(day)
    records = log.read_day(day)
    summary = aggregate_records(records)
    summary["date"] = day.isoformat()
    summary["record_count"] = len(records)
    return summary


def format_text_report(summary: dict[str, Any]) -> str:
    lines = [
        f"auto-workflow usage {summary.get('date')}",
        f"  started={summary.get('runs_started')} finished={summary.get('runs_finished')} "
        f"failures={summary.get('failures')} timeouts={summary.get('timeouts')} "
        f"unknown={summary.get('unknown_outcomes')} unfinished={summary.get('unfinished')}",
        f"  duration_known={summary.get('duration_known_count')} "
        f"total_s={summary.get('duration_total_seconds')} "
        f"avg_s={summary.get('duration_average_seconds')}",
        f"  by_prompt_class={summary.get('by_prompt_class')}",
        f"  by_mode={summary.get('by_mode')}",
    ]
    if summary.get("malformed_or_skipped"):
        lines.append(f"  malformed_or_skipped={summary['malformed_or_skipped']}")
    return "\n".join(lines)


def write_summary(
    log_dir: Path | str,
    day: date | str,
    *,
    summary: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    log = RunLog(log_dir)
    if summary is None:
        summary = build_summary_for_day(log, day)
    if isinstance(day, str):
        day = date.fromisoformat(day)
    out_dir = ensure_dir(Path(log_dir) / "summaries")
    out_path = out_dir / f"{day.isoformat()}.json"
    _atomic_write_json(out_path, summary)
    return out_path, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument(
        "--date",
        default=None,
        help="UTC date YYYY-MM-DD (default: yesterday UTC)",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else _repo_root_from_script()
    cfg = load_config(repo_root)
    log_dir = resolve_path(repo_root, cfg["log_dir"])

    if args.date:
        day = date.fromisoformat(args.date)
    else:
        # Default: previous UTC day so the nightly job after midnight covers a full day.
        day = datetime.now(timezone.utc).date()
        from datetime import timedelta

        day = day - timedelta(days=1)

    maintenance = cfg.get("maintenance") or {}
    summary_cfg = maintenance.get("summary") or {}
    if summary_cfg.get("enabled") is False:
        print("usage summary disabled in config")
        return 0

    path, summary = write_summary(log_dir, day)
    print(format_text_report(summary))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
