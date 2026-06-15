from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from config import project_path
from modules.auto_qc import recent_auto_qc_runs
from modules.batch_qc import recent_batches
from modules.event_bus import recent_events
from modules.health_engine import system_health
from modules.job_runner import operator_state
from modules.log_center import recent_logs
from modules.queue_engine import queue_stats
from modules.replace_diagnostics import replace_diagnostics
from modules.watch_folder import DEFAULT_STATE_FILE, load_state


MEDIA_SUFFIXES = (".mp4", ".mov", ".avi", ".mkv", ".webm")
DB_SUFFIXES = (".sqlite", ".sqlite3", ".db")
SECRET_KEYS = ("secret", "token", "password", "api_key", "apikey", "authorization")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _safe(label: str, factory, fallback):
    try:
        return factory()
    except Exception as exc:
        return {**fallback, "error": f"{label}: {exc}"}


def sanitize_for_diagnostics(value, key: str = ""):
    lowered_key = key.lower()
    if any(part in lowered_key for part in SECRET_KEYS):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(k): sanitize_for_diagnostics(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_for_diagnostics(item, key) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        if any(suffix in lowered for suffix in MEDIA_SUFFIXES):
            return "[media path omitted]"
        if any(suffix in lowered for suffix in DB_SUFFIXES):
            return "[database path omitted]"
    return value


def _paths(payload: dict | None) -> dict:
    paths = (payload or {}).get("paths") or {}
    allowed = {}
    for key, value in paths.items():
        lowered = str(value).lower()
        if any(suffix in lowered for suffix in MEDIA_SUFFIXES + DB_SUFFIXES):
            continue
        allowed[key] = value
    return allowed


def _run_digest(payload: dict | None, id_key: str) -> dict:
    if not payload:
        return {}
    return sanitize_for_diagnostics(
        {
            id_key: payload.get(id_key),
            "created_at": payload.get("created_at"),
            "output_dir": payload.get("output_dir"),
            "counts": payload.get("counts") or {},
            "paths": _paths(payload),
            "clip_count": len(payload.get("clips") or []),
        }
    )


def _watch_summary() -> dict:
    state = load_state(DEFAULT_STATE_FILE)
    files = state.get("files") or {}
    statuses: dict[str, int] = {}
    for entry in files.values():
        status = entry.get("status") or "unknown"
        statuses[status] = statuses.get(status, 0) + 1
    return {"state_file": str(DEFAULT_STATE_FILE), "file_count": len(files), "statuses": statuses}


def _repo_safety() -> dict:
    try:
        from tools.check_repo_safety import check_repo

        return check_repo(cwd=project_path("."))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _dead_code() -> dict:
    try:
        from tools.dead_code_audit import audit

        return audit(project_path("."))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def recommendations(snapshot: dict) -> list[str]:
    output = []
    latest = snapshot.get("latest_runs") or {}
    if not latest.get("auto_qc"):
        output.append("Run Auto QC once after confirming the input folder.")
    if not latest.get("batch_qc"):
        output.append("Run Batch QC once to build a portfolio view.")
    replace = snapshot.get("replace") or {}
    if replace.get("missing_backups"):
        output.append("Resolve missing Safe Replace backups before rollback.")
    if not output:
        output.append("Review latest run counts, rejected clips, and replace status.")
    return output


def production_diagnostics_snapshot(*, include_checks: bool = True) -> dict:
    auto_runs = _safe("auto_qc", lambda: recent_auto_qc_runs(limit=1), [])
    batch_runs = _safe("batch_qc", lambda: recent_batches(limit=1), [])
    latest_auto = auto_runs[0] if isinstance(auto_runs, list) and auto_runs else {}
    latest_batch = batch_runs[0] if isinstance(batch_runs, list) and batch_runs else {}
    snapshot = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "latest_runs": {
            "auto_qc": _run_digest(latest_auto, "run_id"),
            "batch_qc": _run_digest(latest_batch, "batch_id"),
        },
        "replace": sanitize_for_diagnostics(_safe("replace", replace_diagnostics, {"ok": False})),
        "queue": sanitize_for_diagnostics(_safe("queue", queue_stats, {"total": 0, "counts": {}, "items": []})),
        "jobs": sanitize_for_diagnostics(_safe("jobs", operator_state, {"jobs": []})),
        "health": sanitize_for_diagnostics(_safe("health", system_health, {"state": "unknown"})),
        "watch_state": sanitize_for_diagnostics(_safe("watch_state", _watch_summary, {"file_count": 0, "statuses": {}})),
        "recent_logs": sanitize_for_diagnostics(_safe("logs", lambda: recent_logs(limit=20), [])),
        "recent_events": sanitize_for_diagnostics(_safe("events", lambda: recent_events(limit=20), [])),
        "generated_report_paths": sanitize_for_diagnostics(
            {
                "auto_qc": _paths(latest_auto),
                "batch_qc": _paths(latest_batch),
            }
        ),
    }
    if include_checks:
        snapshot["repo_safety"] = sanitize_for_diagnostics(_repo_safety())
        snapshot["dead_code_quarantine"] = sanitize_for_diagnostics(_dead_code())
    snapshot["recommendations"] = recommendations(snapshot)
    return snapshot


def diagnostics_summary_text(snapshot: dict) -> str:
    latest = snapshot.get("latest_runs") or {}
    auto_qc = latest.get("auto_qc") or {}
    batch_qc = latest.get("batch_qc") or {}
    replace = snapshot.get("replace") or {}
    queue = snapshot.get("queue") or {}
    jobs = snapshot.get("jobs") or {}
    health = snapshot.get("health") or {}
    lines = [
        "Production Diagnostics",
        f"generated_at: {snapshot.get('generated_at')}",
        f"latest_auto_qc: {auto_qc.get('run_id') or '-'}",
        f"latest_batch_qc: {batch_qc.get('batch_id') or '-'}",
        f"replace_status: {replace.get('status')}",
        f"replace_replacements: {replace.get('total_replacements', 0)}",
        f"queue_total: {queue.get('total', 0)}",
        f"current_job: {(jobs.get('current_job') or {}).get('job_type') or '-'}",
        f"health: {health.get('state')}",
        "recommendations:",
    ]
    lines.extend(f"- {item}" for item in snapshot.get("recommendations") or [])
    return "\n".join(lines)


def export_production_diagnostics(output_dir: str | Path = project_path("data/diagnostics")) -> dict:
    snapshot = production_diagnostics_snapshot(include_checks=True)
    root = Path(output_dir) / f"diagnostics_{utc_stamp()}"
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "diagnostics.json"
    text_path = root / "diagnostics_summary.txt"
    json_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    text_path.write_text(diagnostics_summary_text(snapshot), encoding="utf-8")
    return {"ok": True, "output_dir": str(root), "diagnostics_json": str(json_path), "diagnostics_summary": str(text_path), "snapshot": snapshot}
