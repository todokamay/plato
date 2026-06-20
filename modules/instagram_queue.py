from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import project_path


QUEUE_DIR = project_path("data/instagram_queue")
QUEUE_FILE = QUEUE_DIR / "queue.json"
SUMMARY_FILE = QUEUE_DIR / "queue_summary.json"
STATUSES = {"queued", "posting", "posted", "posted_dry_run", "failed", "skipped"}
PUBLISH_VERDICTS = {"STRONG PUBLISH", "PUBLISH"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_queue() -> dict:
    return {"version": 1, "updated_at": utc_now(), "items": []}


def load_queue(queue_file: str | Path = QUEUE_FILE) -> dict:
    path = Path(queue_file)
    if not path.exists():
        return _empty_queue()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_queue()
    if isinstance(data, list):
        data = {"version": 1, "items": data}
    if not isinstance(data, dict):
        return _empty_queue()
    data.setdefault("version", 1)
    data.setdefault("updated_at", utc_now())
    data.setdefault("items", [])
    return data


def save_queue(queue: dict, queue_file: str | Path = QUEUE_FILE) -> None:
    path = Path(queue_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    queue["updated_at"] = utc_now()
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _norm_path(value: str | Path | None) -> str:
    return str(Path(str(value or "")).resolve()).lower() if str(value or "").strip() else ""


def _allow_safe_to_test(allow_safe_to_test: bool | None = None) -> bool:
    if allow_safe_to_test is not None:
        return bool(allow_safe_to_test)
    return str(os.environ.get("ALLOW_SAFE_TO_TEST") or "").strip().lower() in {"1", "true", "yes", "on"}


def _hashtags(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").replace(",", " ").split() if item.strip()]


def _looks_raw(path: str) -> bool:
    lowered = path.replace("\\", "/").lower()
    parts = set(lowered.split("/"))
    return bool(parts & {"raw", "longvideos"}) or "_raw" in Path(lowered).stem


def _publishable(row: dict, allow_safe_to_test: bool | None = None) -> tuple[bool, str]:
    verdict = str(row.get("plato_verdict") or row.get("verdict") or "").strip().upper()
    if verdict in PUBLISH_VERDICTS:
        return True, ""
    if verdict == "SAFE TO TEST" and _allow_safe_to_test(allow_safe_to_test):
        return True, ""
    return False, f"verdict {verdict or 'missing'} is not queue-eligible"


def build_queue_item(row: dict, *, allow_safe_to_test: bool | None = None) -> tuple[dict | None, str]:
    approved = str(row.get("approved_output_path") or "").strip()
    if not approved:
        return None, "approved_output_path is empty"
    if row.get("source_final_path") and _norm_path(approved) == _norm_path(row.get("source_final_path")):
        return None, "approved_output_path is source_final_path"
    if _looks_raw(approved):
        return None, "approved_output_path looks raw/source"
    ok, reason = _publishable(row, allow_safe_to_test)
    if not ok:
        return None, reason
    return {
        "job_id": str(row.get("job_id") or uuid.uuid4().hex),
        "approved_output_path": approved,
        "caption": str(row.get("caption") or row.get("copy_ready_description") or ""),
        "hashtags": _hashtags(row.get("hashtags") or row.get("hashtags_suggestion")),
        "score": row.get("plato_score") or row.get("score") or 0,
        "verdict": str(row.get("plato_verdict") or row.get("verdict") or ""),
        "created_at": utc_now(),
        "scheduled_at": str(row.get("scheduled_at") or ""),
        "status": "queued",
        "attempts": 0,
        "error": "",
    }, ""


def enqueue(item: dict, *, queue_file: str | Path = QUEUE_FILE, force: bool = False) -> tuple[dict, bool]:
    queue = load_queue(queue_file)
    key = _norm_path(item.get("approved_output_path"))
    for index, existing in enumerate(queue.get("items", [])):
        if _norm_path(existing.get("approved_output_path")) != key:
            continue
        if force:
            merged = {**existing, **item, "created_at": existing.get("created_at") or item.get("created_at") or utc_now()}
            queue["items"][index] = merged
            save_queue(queue, queue_file)
            export_summary(queue_file=queue_file)
            return merged, True
        return existing, False
    queue["items"].append(item)
    save_queue(queue, queue_file)
    export_summary(queue_file=queue_file)
    return item, True


def mark_state(job_id: str, status: str, *, error: str = "", queue_file: str | Path = QUEUE_FILE) -> dict:
    if status not in STATUSES:
        raise ValueError(f"Unsupported Instagram queue status: {status}")
    queue = load_queue(queue_file)
    for item in queue.get("items", []):
        if item.get("job_id") != job_id:
            continue
        item["status"] = status
        item["error"] = str(error or "")
        if status in {"posting", "failed"}:
            item["attempts"] = int(item.get("attempts") or 0) + 1
        save_queue(queue, queue_file)
        export_summary(queue_file=queue_file)
        return item
    raise KeyError(f"Instagram queue item not found: {job_id}")


def list_items(queue_file: str | Path = QUEUE_FILE) -> list[dict]:
    return list(load_queue(queue_file).get("items", []))


def get_stats(queue_file: str | Path = QUEUE_FILE) -> dict:
    items = list_items(queue_file)
    counts = {status: 0 for status in STATUSES}
    for item in items:
        counts[str(item.get("status") or "queued")] = counts.get(str(item.get("status") or "queued"), 0) + 1
    latest = items[-1] if items else None
    return {"total": len(items), "counts": counts, "latest": latest, "items": items}


def export_summary(
    *,
    queue_file: str | Path = QUEUE_FILE,
    summary_file: str | Path | None = None,
) -> dict:
    summary = {"updated_at": utc_now(), **get_stats(queue_file)}
    path = Path(summary_file) if summary_file else Path(queue_file).with_name("queue_summary.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
