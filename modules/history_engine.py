from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import project_path


DEFAULT_HISTORY_LOG = project_path("data/history/history.jsonl")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_history(
    clip_identity: str,
    *,
    action: str,
    status: str,
    details: dict | None = None,
    history_log: str | Path = DEFAULT_HISTORY_LOG,
) -> dict:
    entry = {
        "history_id": uuid.uuid4().hex,
        "clip_identity": clip_identity,
        "action": action,
        "status": status,
        "details": details or {},
        "created_at": utc_now(),
    }
    path = Path(history_log)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


def history_entries(clip_identity: str | None = None, *, limit: int = 100, history_log: str | Path = DEFAULT_HISTORY_LOG) -> list[dict]:
    path = Path(history_log)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if clip_identity is None or item.get("clip_identity") == clip_identity:
            rows.append(item)
    return rows[-limit:]


def history_summary(*, history_log: str | Path = DEFAULT_HISTORY_LOG) -> dict:
    rows = history_entries(limit=100000, history_log=history_log)
    by_status: dict[str, int] = {}
    by_action: dict[str, int] = {}
    for row in rows:
        by_status[row.get("status", "")] = by_status.get(row.get("status", ""), 0) + 1
        by_action[row.get("action", "")] = by_action.get(row.get("action", ""), 0) + 1
    return {"total": len(rows), "by_status": by_status, "by_action": by_action, "recent": rows[-20:]}
