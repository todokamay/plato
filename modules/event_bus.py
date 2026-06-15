from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import project_path


EVENT_TYPES = {
    "detected",
    "started",
    "fixed",
    "accepted",
    "rejected",
    "rerouted",
    "failed",
    "completed",
    "success",
    "state_changed",
    "paused",
    "stopped",
    "recovered",
}
DEFAULT_EVENT_LOG = project_path("data/events/events.jsonl")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _event(event_type: str, payload: dict | None = None, source: str = "factory") -> dict:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unsupported event type: {event_type}")
    return {
        "event_id": uuid.uuid4().hex,
        "event_type": event_type,
        "source": source,
        "created_at": utc_now(),
        "payload": payload or {},
    }


def publish_event(event_type: str, payload: dict | None = None, *, source: str = "factory", log_path: str | Path = DEFAULT_EVENT_LOG) -> dict:
    event = _event(event_type, payload, source)
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def recent_events(limit: int = 50, *, log_path: str | Path = DEFAULT_EVENT_LOG) -> list[dict]:
    path = Path(log_path)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]


class EventBus:
    def __init__(self, log_path: str | Path = DEFAULT_EVENT_LOG):
        self.log_path = Path(log_path)

    def publish(self, event_type: str, payload: dict | None = None, source: str = "factory") -> dict:
        return publish_event(event_type, payload, source=source, log_path=self.log_path)

    def recent(self, limit: int = 50) -> list[dict]:
        return recent_events(limit, log_path=self.log_path)
