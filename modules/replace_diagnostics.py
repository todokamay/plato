from __future__ import annotations

import json
from pathlib import Path

from config import project_path


def _latest_log() -> Path | None:
    candidates = list(project_path("data/auto_qc_runs").glob("*/logs/replace_log.json"))
    candidates += [path for path in [project_path("logs/replace_log.json"), project_path("data/logs/replace_log.json")] if path.exists()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def replace_diagnostics(log_path: str | Path | None = None) -> dict:
    path = Path(log_path) if log_path else _latest_log()
    if not path or not path.exists():
        return {
            "ok": True,
            "status": "never_used",
            "message": "replace mode never used",
            "latest_log": "",
            "total_replacements": 0,
            "replaced_files": [],
            "backup_files": [],
            "missing_backups": [],
            "rollback_available": False,
            "last_replace_time": "",
            "failed_replacements": [],
            "skipped_replacements": [],
        }

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "status": "error", "latest_log": str(path), "error": str(exc)}

    items = payload.get("items") or []
    replaced = [item for item in items if item.get("status") == "replaced"]
    skipped = [item for item in items if item.get("status") != "replaced"]
    backup_files = [item.get("backup_path", "") for item in replaced if item.get("backup_path")]
    missing_backups = [backup for backup in backup_files if not Path(backup).exists()]
    failed = [item for item in skipped if item.get("reason") not in {"fixed clip was not accepted", "--confirm-replace is required"}]
    return {
        "ok": True,
        "status": "used" if items else "empty_log",
        "message": "latest replace log loaded",
        "latest_log": str(path),
        "total_replacements": len(replaced),
        "replaced_files": [item.get("original_path", "") for item in replaced],
        "backup_files": backup_files,
        "missing_backups": missing_backups,
        "rollback_available": bool(replaced) and not missing_backups,
        "last_replace_time": payload.get("created_at", ""),
        "failed_replacements": failed,
        "skipped_replacements": skipped,
    }


def summary_text(summary: dict) -> str:
    if not summary.get("ok"):
        return f"Replace diagnostics error: {summary.get('error', 'unknown error')}"
    lines = [
        "Replace Diagnostics",
        f"status: {summary.get('status')}",
        f"latest_log: {summary.get('latest_log') or '-'}",
        f"total_replacements: {summary.get('total_replacements', 0)}",
        f"rollback_available: {summary.get('rollback_available')}",
        f"missing_backups: {len(summary.get('missing_backups') or [])}",
        f"failed_replacements: {len(summary.get('failed_replacements') or [])}",
        f"skipped_replacements: {len(summary.get('skipped_replacements') or [])}",
    ]
    return "\n".join(lines)
