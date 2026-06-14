from __future__ import annotations

import shutil
from pathlib import Path

from config import project_path
from modules.queue_engine import queue_stats


HEALTH_STATES = {"healthy", "warning", "critical"}


def disk_health(path: str | Path = project_path("."), *, warning_free_ratio: float = 0.15, critical_free_ratio: float = 0.05) -> dict:
    usage = shutil.disk_usage(path)
    free_ratio = usage.free / usage.total if usage.total else 0
    if free_ratio <= critical_free_ratio:
        state = "critical"
    elif free_ratio <= warning_free_ratio:
        state = "warning"
    else:
        state = "healthy"
    return {
        "state": state,
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "free_ratio": round(free_ratio, 4),
    }


def system_health(*, queue_file: str | Path | None = None, watch_state: dict | None = None) -> dict:
    disk = disk_health()
    queue = queue_stats(queue_file) if queue_file else queue_stats()
    failed = (queue.get("counts") or {}).get("failed", 0)
    processing = (queue.get("counts") or {}).get("processing", 0)
    state = disk["state"]
    if failed:
        state = "critical"
    elif processing > 20 and state == "healthy":
        state = "warning"
    return {
        "state": state,
        "disk": disk,
        "cpu": {"state": "healthy", "note": "standard-library monitor"},
        "ram": {"state": "healthy", "note": "standard-library monitor"},
        "queue": queue,
        "watch": watch_state or {},
        "pipeline": {"state": "healthy" if state != "critical" else "critical"},
    }
