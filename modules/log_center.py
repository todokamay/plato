from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import project_path


DEFAULT_LOG_DIR = project_path("data/logs")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_log(message: str, *, level: str = "INFO", source: str = "factory", log_dir: str | Path = DEFAULT_LOG_DIR) -> dict:
    entry = {"created_at": utc_now(), "level": level.upper(), "source": source, "message": message}
    root = Path(log_dir)
    root.mkdir(parents=True, exist_ok=True)
    with (root / "factory.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    with (root / "factory.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{entry['created_at']} [{entry['level']}] {source}: {message}\n")
    csv_path = root / "factory.csv"
    write_header = not csv_path.exists()
    with csv_path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["created_at", "level", "source", "message"])
        if write_header:
            writer.writeheader()
        writer.writerow(entry)
    return entry


def recent_logs(limit: int = 100, *, log_dir: str | Path = DEFAULT_LOG_DIR) -> list[dict]:
    path = Path(log_dir) / "factory.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]


def cleanup_logs(retention_days: int = 30, *, log_dir: str | Path = DEFAULT_LOG_DIR) -> list[str]:
    root = Path(log_dir)
    if not root.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = []
    for path in root.glob("*.old"):
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if modified < cutoff:
            path.unlink(missing_ok=True)
            removed.append(str(path))
    return removed
