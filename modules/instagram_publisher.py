from __future__ import annotations

import json
import os
from pathlib import Path

from modules.instagram_queue import QUEUE_FILE, export_summary, load_queue, save_queue, utc_now


POSTED_FILE = QUEUE_FILE.with_name("posted.json")
FAILED_FILE = QUEUE_FILE.with_name("failed.json")
PUBLISH_VERDICTS = {"STRONG PUBLISH", "PUBLISH"}
MAX_CAPTION_LENGTH = 2200


def _allow_safe_to_test(value: bool = False) -> bool:
    if value:
        return True
    return str(os.environ.get("ALLOW_SAFE_TO_TEST") or "").strip().lower() in {"1", "true", "yes", "on"}


def _unsafe_path(path: str) -> bool:
    lowered = path.replace("\\", "/").lower()
    parts = set(lowered.split("/"))
    return bool(parts & {"raw", "source", "longvideos", "rendered", "subtitled", "intermediate"}) or "_raw" in Path(lowered).stem


def get_next_queue_item(queue: dict) -> dict | None:
    for item in queue.get("items", []):
        if isinstance(item, dict) and item.get("status") == "queued":
            return item
    return None


def validate_publish_item(item: dict, *, allow_safe_to_test: bool = False) -> tuple[bool, str]:
    if not isinstance(item, dict):
        return False, "queue item malformed"
    if not str(item.get("job_id") or "").strip():
        return False, "queue item malformed: missing job_id"
    if item.get("status") != "queued":
        return False, "status is not queued"
    approved = str(item.get("approved_output_path") or "").strip()
    if not approved:
        return False, "approved_output_path empty"
    path = Path(approved)
    if not path.exists():
        return False, "approved_output_path missing"
    if path.suffix.lower() != ".mp4":
        return False, "approved_output_path is not .mp4"
    if _unsafe_path(approved):
        return False, "approved_output_path looks raw/source/intermediate"
    verdict = str(item.get("verdict") or "").strip().upper()
    if verdict not in PUBLISH_VERDICTS and not (verdict == "SAFE TO TEST" and _allow_safe_to_test(allow_safe_to_test)):
        return False, f"verdict {verdict or 'missing'} is not publishable"
    if len(str(item.get("caption") or "")) > MAX_CAPTION_LENGTH:
        return False, "caption too long"
    return True, ""


def _append_json(path: Path, row: dict) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, json.JSONDecodeError):
        data = []
    if not isinstance(data, list):
        data = []
    data.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_publish_summary(result: dict, *, queue_path: str | Path | None = None) -> None:
    queue_file = Path(queue_path or QUEUE_FILE)
    path = queue_file.with_name("posted.json" if result.get("ok") else "failed.json")
    _append_json(path, result)


def latest_publish_result(queue_path: str | Path | None = None) -> dict:
    queue_file = Path(queue_path or QUEUE_FILE)
    candidates = []
    for name in ("posted.json", "failed.json"):
        path = queue_file.with_name(name)
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        except (OSError, json.JSONDecodeError):
            data = []
        if isinstance(data, list) and data:
            candidates.append(data[-1])
    candidates.sort(key=lambda item: item.get("at") or "")
    return candidates[-1] if candidates else {}


def _update_item(queue: dict, item: dict, status: str, error: str = "") -> dict:
    now = utc_now()
    item["status"] = status
    item["attempts"] = int(item.get("attempts") or 0) + 1
    item["last_attempt_at"] = now
    item["error"] = error
    if status == "posted_dry_run":
        item["posted_at"] = now
    return item


def publish_one_dry_run(queue_path: str | Path | None = None, *, allow_safe_to_test: bool = False) -> dict:
    queue_file = Path(queue_path or QUEUE_FILE)
    queue = load_queue(queue_file)
    item = get_next_queue_item(queue)
    if not item:
        return {"ok": True, "dry_run": True, "published": False, "status": "no_item", "reason": "no queued items"}
    ok, reason = validate_publish_item(item, allow_safe_to_test=allow_safe_to_test)
    if not ok:
        _update_item(queue, item, "failed", reason)
        save_queue(queue, queue_file)
        export_summary(queue_file=queue_file)
        result = {
            "ok": False,
            "at": utc_now(),
            "dry_run": True,
            "published": False,
            "status": "failed",
            "job_id": item.get("job_id", ""),
            "approved_output_path": item.get("approved_output_path", ""),
            "reason": reason,
        }
        write_publish_summary(result, queue_path=queue_file)
        return result
    _update_item(queue, item, "posted_dry_run", "")
    save_queue(queue, queue_file)
    export_summary(queue_file=queue_file)
    result = {
        "ok": True,
        "at": utc_now(),
        "dry_run": True,
        "published": False,
        "status": "posted_dry_run",
        "job_id": item["job_id"],
        "approved_output_path": item["approved_output_path"],
        "reason": "dry-run publish simulated",
    }
    write_publish_summary(result, queue_path=queue_file)
    return result
