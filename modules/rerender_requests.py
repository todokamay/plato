from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from config import project_path


STATUSES = {"requested", "accepted", "completed", "failed", "skipped"}


def rerender_root(root: str | Path | None = None) -> Path:
    return Path(root or os.environ.get("PLATO_RERENDER_REQUEST_ROOT") or project_path("data/rerender_requests"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value or "job")).strip("_")
    return value or "job"


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def ensure_rerender_dirs(root: str | Path | None = None) -> Path:
    base = rerender_root(root)
    for status in STATUSES:
        (base / status).mkdir(parents=True, exist_ok=True)
    return base


def _requested_changes(blocker_type: str, reason: str) -> list[str]:
    text = f"{blocker_type} {reason}".lower()
    if "unsafe banner" in text:
        return ["move_banner_to_safe_zone", "rerender_ad_banner"]
    if "subtitle overlap" in text or "subtitle" in text:
        return ["rerender_subtitles", "adjust_subtitle_position"]
    if "wrong layout" in text or "layout" in text:
        return ["rerender_vertical_layout", "enforce_1080x1920"]
    if "bad crop" in text or "crop" in text:
        return ["rerender_crop", "adjust_reframe"]
    if "davinci" in text or "render issue" in text or "rerender" in text:
        return ["rerun_davinci", "verify_final_output"]
    return ["manual_review"]


def _score(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _source_video(delivery_job: dict) -> str:
    status = delivery_job.get("status") if isinstance(delivery_job.get("status"), dict) else {}
    for key in ["source_video", "input_path", "input_video", "original_input_path"]:
        if delivery_job.get(key):
            return str(delivery_job[key])
        if status.get(key):
            return str(status[key])
    return ""


def build_rerender_request(delivery_job: dict, route_result: dict) -> dict:
    if (route_result or {}).get("route") != "vap_rerender":
        return {}
    source_final_path = str(delivery_job.get("source_final_path") or delivery_job.get("final_path") or "")
    if not source_final_path:
        return {}

    now = _now()
    job_id = str(delivery_job.get("job_id") or "")
    blocker_type = str(route_result.get("blocker_type") or delivery_job.get("blocker_type") or "unknown")
    blocker_reason = str(route_result.get("reason") or delivery_job.get("blocker_next_action") or delivery_job.get("reason") or "")
    return {
        "schema_version": 1,
        "request_id": f"rerender_{_stamp()}_{_slug(job_id)}",
        "job_id": job_id,
        "source_video": _source_video(delivery_job),
        "source_final_path": source_final_path,
        "approved_output_path": str(delivery_job.get("approved_output_path") or ""),
        "plato_score": _score(delivery_job.get("plato_score")),
        "plato_verdict": str(delivery_job.get("plato_verdict") or ""),
        "plato_bucket": str(delivery_job.get("plato_bucket") or ""),
        "blocker_type": blocker_type,
        "blocker_reason": blocker_reason,
        "requested_changes": _requested_changes(blocker_type, blocker_reason),
        "priority": "normal",
        "status": "requested",
        "created_at": now,
        "updated_at": now,
        "created_by": "plato",
        "safe_to_retry": True,
        "notes": "",
    }


def _same_request(left: dict, right: dict) -> bool:
    return (
        str(left.get("job_id") or "") == str(right.get("job_id") or "")
        and str(left.get("blocker_type") or "").lower() == str(right.get("blocker_type") or "").lower()
        and str(left.get("source_final_path") or "").lower() == str(right.get("source_final_path") or "").lower()
    )


def _find_duplicate(request: dict, root: str | Path | None = None) -> tuple[dict, Path] | tuple[None, None]:
    base = rerender_root(root)
    for status in STATUSES:
        for path in (base / status).glob("*.json"):
            existing = _read_json(path)
            if existing and _same_request(existing, request):
                return existing, path
    return None, None


def write_rerender_request(request: dict, root: str | Path | None = None) -> dict:
    if not request:
        return {"ok": False, "created": False, "path": "", "request": {}, "reason": "empty request"}
    existing, existing_path = _find_duplicate(request, root)
    if existing and existing_path:
        return {"ok": True, "created": False, "path": str(existing_path), "request": existing}
    base = ensure_rerender_dirs(root)
    status = str(request.get("status") or "requested")
    if status not in STATUSES:
        status = "requested"
        request["status"] = status
    path = base / status / f"{request['request_id']}.json"
    _write_json_atomic(path, request)
    return {"ok": True, "created": True, "path": str(path), "request": request}


def list_rerender_requests(status: str = "requested", root: str | Path | None = None) -> list[dict]:
    base = rerender_root(root)
    statuses = STATUSES if status in {"", "all", "*"} else {status}
    items = []
    for item_status in statuses:
        if item_status not in STATUSES:
            continue
        for path in (base / item_status).glob("*.json"):
            request = _read_json(path)
            if request:
                items.append({**request, "path": str(path)})
    return sorted(items, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def get_rerender_stats(root: str | Path | None = None) -> dict:
    counts = {status: len(list_rerender_requests(status, root)) for status in sorted(STATUSES)}
    items = list_rerender_requests("all", root)
    latest = items[0] if items else {}
    return {"total": sum(counts.values()), "counts": counts, "latest": latest, "items": items[:20]}


def mark_request_status(request_id: str, status: str, reason: str = "", root: str | Path | None = None, updates: dict | None = None) -> dict:
    if status not in STATUSES:
        raise ValueError(f"Unknown rerender request status: {status}")
    base = ensure_rerender_dirs(root)
    for current in STATUSES:
        path = base / current / f"{request_id}.json"
        request = _read_json(path)
        if not request:
            continue
        request["status"] = status
        request["updated_at"] = _now()
        if updates:
            request.update(updates)
        if reason:
            request["notes"] = reason
        target = base / status / path.name
        _write_json_atomic(target, request)
        if target != path:
            path.unlink(missing_ok=True)
        return {"ok": True, "path": str(target), "request": request}
    return {"ok": False, "path": "", "request": {}, "reason": "request not found"}
