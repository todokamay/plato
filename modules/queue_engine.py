from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import project_path


QUEUE_STATES = {"queued", "processing", "waiting", "success", "failed", "retry", "cancelled"}
DEFAULT_QUEUE_DIR = project_path("data/queue")
DEFAULT_QUEUE_FILE = DEFAULT_QUEUE_DIR / "queue.json"
DEFAULT_DEAD_LETTER_FILE = DEFAULT_QUEUE_DIR / "dead_letters.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_queue() -> dict:
    return {"version": 1, "updated_at": utc_now(), "items": []}


def load_queue(queue_file: str | Path = DEFAULT_QUEUE_FILE) -> dict:
    path = Path(queue_file)
    if not path.exists():
        return _empty_queue()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_queue()
    if not isinstance(data, dict):
        return _empty_queue()
    data.setdefault("version", 1)
    data.setdefault("items", [])
    return data


def save_queue(queue: dict, queue_file: str | Path = DEFAULT_QUEUE_FILE) -> None:
    path = Path(queue_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    queue["updated_at"] = utc_now()
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _find_by_path(queue: dict, file_path: str) -> dict | None:
    resolved = str(Path(file_path).resolve())
    for item in queue.get("items", []):
        if item.get("file_path") == resolved and item.get("state") not in {"success", "cancelled"}:
            return item
    return None


def enqueue(
    file_path: str | Path,
    *,
    priority: int = 50,
    source: str = "watch",
    queue_file: str | Path = DEFAULT_QUEUE_FILE,
) -> dict:
    queue = load_queue(queue_file)
    resolved = str(Path(file_path).resolve())
    existing = _find_by_path(queue, resolved)
    if existing:
        return existing
    item = {
        "job_id": uuid.uuid4().hex,
        "file_path": resolved,
        "priority": int(priority),
        "base_priority": int(priority),
        "source": source,
        "state": "queued",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "attempts": 0,
        "max_attempts": 3,
        "last_error": "",
        "run_id": "",
        "history": [],
    }
    queue["items"].append(item)
    save_queue(queue, queue_file)
    return item


def queued_items(*, limit: int | None = None, queue_file: str | Path = DEFAULT_QUEUE_FILE) -> list[dict]:
    queue = load_queue(queue_file)
    candidates = [item for item in queue.get("items", []) if item.get("state") in {"queued", "retry"}]
    candidates.sort(key=lambda item: (-int(item.get("priority") or 0), item.get("created_at") or ""))
    return candidates[:limit] if limit else candidates


def update_job(job_id: str, state: str, *, result: dict | None = None, queue_file: str | Path = DEFAULT_QUEUE_FILE) -> dict:
    if state not in QUEUE_STATES:
        raise ValueError(f"Unsupported queue state: {state}")
    queue = load_queue(queue_file)
    for item in queue.get("items", []):
        if item.get("job_id") != job_id:
            continue
        item["state"] = state
        item["updated_at"] = utc_now()
        if state == "processing":
            item["attempts"] = int(item.get("attempts") or 0) + 1
        if result:
            item["run_id"] = result.get("run_id", item.get("run_id", ""))
            item["last_error"] = result.get("error", "")
            item.setdefault("history", []).append({"state": state, "at": utc_now(), "result": result})
        save_queue(queue, queue_file)
        return item
    raise KeyError(f"Queue job not found: {job_id}")


def retry_or_dead_letter(job_id: str, error: str, *, queue_file: str | Path = DEFAULT_QUEUE_FILE, dead_letter_file: str | Path = DEFAULT_DEAD_LETTER_FILE) -> dict:
    queue = load_queue(queue_file)
    for item in queue.get("items", []):
        if item.get("job_id") != job_id:
            continue
        attempts = int(item.get("attempts") or 0)
        max_attempts = int(item.get("max_attempts") or 3)
        if attempts < max_attempts:
            item["state"] = "retry"
            item["last_error"] = error
            item["updated_at"] = utc_now()
            save_queue(queue, queue_file)
            return item
        item["state"] = "failed"
        item["last_error"] = error
        item["updated_at"] = utc_now()
        dead = _load_dead_letters(dead_letter_file)
        dead["items"].append(item.copy())
        _save_dead_letters(dead, dead_letter_file)
        save_queue(queue, queue_file)
        return item
    raise KeyError(f"Queue job not found: {job_id}")


def _load_dead_letters(path: str | Path = DEFAULT_DEAD_LETTER_FILE) -> dict:
    dead_path = Path(path)
    if not dead_path.exists():
        return {"version": 1, "updated_at": utc_now(), "items": []}
    try:
        data = json.loads(dead_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "updated_at": utc_now(), "items": []}
    data.setdefault("items", [])
    return data


def _save_dead_letters(data: dict, path: str | Path = DEFAULT_DEAD_LETTER_FILE) -> None:
    dead_path = Path(path)
    dead_path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = utc_now()
    dead_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def queue_stats(queue_file: str | Path = DEFAULT_QUEUE_FILE) -> dict:
    queue = load_queue(queue_file)
    counts = {state: 0 for state in QUEUE_STATES}
    for item in queue.get("items", []):
        state = item.get("state") or "queued"
        counts[state] = counts.get(state, 0) + 1
    return {"total": len(queue.get("items", [])), "counts": counts, "items": queue.get("items", [])}


class QueueEngine:
    def __init__(self, queue_file: str | Path = DEFAULT_QUEUE_FILE):
        self.queue_file = Path(queue_file)

    def enqueue(self, file_path: str | Path, priority: int = 50, source: str = "watch") -> dict:
        return enqueue(file_path, priority=priority, source=source, queue_file=self.queue_file)

    def next(self, limit: int = 1) -> list[dict]:
        return queued_items(limit=limit, queue_file=self.queue_file)

    def update(self, job_id: str, state: str, result: dict | None = None) -> dict:
        return update_job(job_id, state, result=result, queue_file=self.queue_file)

    def stats(self) -> dict:
        return queue_stats(self.queue_file)
