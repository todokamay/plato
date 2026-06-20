from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from config import project_path


CLEANUP_MODES = {"keep_final_only", "keep_all", "dry_run"}
APPROVED_STATUSES = {"approved", "approved_not_sent", "sent", "ready"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return path


def _resolve(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _drive_root(path: Path) -> Path:
    return Path(path.anchor or "\\").resolve()


def _unsafe_root_reason(path: Path, label: str) -> str:
    project_root = project_path(".").resolve()
    home = Path.home().resolve()
    dangerous = {
        str(project_root).lower(): f"Project root is not a safe {label}.",
        str(home).lower(): f"User home root is not a safe {label}.",
        str(_drive_root(path)).lower(): f"Drive root is not a safe {label}.",
    }
    return dangerous.get(str(path).lower(), "")


def _longvideos_path(path: Path) -> bool:
    return any(part.lower() == "longvideos" for part in path.parts)


def _report_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return bool(parts & {"metadata", "status", "reports", "logs"}) or path.suffix.lower() in {".csv", ".log", ".txt"}


def _eligible_rows(payload: dict) -> list[dict]:
    rows = []
    for row in payload.get("jobs") or []:
        approved = str(row.get("approved_output_path") or "")
        status = str(row.get("delivery_status") or "").lower()
        if (
            status in APPROVED_STATUSES
            and approved
            and Path(approved).exists()
        ):
            rows.append(row)
    return rows


def _audit_payload(row: dict) -> dict:
    return {
        "created_at": utc_now(),
        "job_id": row.get("job_id", ""),
        "approved_output_path": row.get("approved_output_path", ""),
        "source_final_path": row.get("source_final_path", ""),
        "delivery_status": row.get("delivery_status", ""),
        "telegram_status": row.get("telegram_status", ""),
        "metadata_path": row.get("metadata_path", ""),
        "status_path": row.get("status_path", ""),
    }


def _target_dirs(output_root: Path, delivery_root: Path, job_id: str) -> list[Path]:
    return [
        output_root / job_id,
        output_root / "jobs" / job_id,
        output_root.parent / "temp" / job_id,
        delivery_root / "qc_runs" / job_id,
    ]


def _iter_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        return [path for path in target.rglob("*") if path.is_file()]
    return []


def cleanup_after_delivery(
    delivery_summary_path: str | Path,
    *,
    mode: str = "keep_all",
    confirm: bool = False,
    allow_source_delete: bool = False,
    cleanup_reports: bool = False,
) -> dict:
    summary_path = _resolve(delivery_summary_path)
    delivery_root = summary_path.parent
    payload = _load_json(summary_path)
    mode = mode if mode in CLEANUP_MODES else "keep_all"
    cleanup_summary_path = project_path("data/cleanup/cleanup_summary.json").resolve()

    result = {
        "ok": True,
        "created_at": utc_now(),
        "mode": mode,
        "dry_run": mode == "dry_run",
        "confirmed": bool(confirm),
        "delivery_summary_path": str(summary_path),
        "eligible_job_count": 0,
        "kept": [],
        "planned_delete": [],
        "deleted": [],
        "skipped": [],
        "errors": [],
        "audit_paths": [],
        "cleanup_summary_path": str(cleanup_summary_path),
    }

    if mode == "keep_all":
        _write_json(cleanup_summary_path, result)
        return result

    output_root_value = payload.get("output_root") or ""
    if not output_root_value:
        result["ok"] = False
        result["errors"].append("delivery_summary.json has no output_root.")
        _write_json(cleanup_summary_path, result)
        return result
    output_root = _resolve(output_root_value)
    for root, label in [(output_root, "output root"), (delivery_root, "delivery root"), (output_root.parent / "temp", "temp root")]:
        reason = _unsafe_root_reason(root, label)
        if reason:
            result["ok"] = False
            result["errors"].append(reason)
    if result["errors"]:
        _write_json(cleanup_summary_path, result)
        return result

    rows = _eligible_rows(payload)
    result["eligible_job_count"] = len(rows)
    if mode == "keep_final_only" and not confirm:
        result["ok"] = False
        result["errors"].append("Cleanup requires --confirm-cleanup.")
    if not rows:
        result["ok"] = mode != "keep_final_only"
        result["skipped"].append("No approved jobs with an existing approved_output_path were found.")

    allowed_roots = [output_root, output_root.parent / "temp", delivery_root]
    instagram_queue_root = project_path("data/instagram_queue").resolve()
    keep: set[str] = {str(summary_path).lower(), str(cleanup_summary_path).lower()}
    audit_dir = cleanup_summary_path.parent / "jobs"
    for row in rows:
        job_id = str(row.get("job_id") or "").strip()
        approved = _resolve(row.get("approved_output_path", ""))
        keep.add(str(approved).lower())
        result["kept"].append(str(approved))
        audit_path = audit_dir / f"{job_id}.audit.json"
        if mode == "keep_final_only" and confirm and result["ok"]:
            _write_json(audit_path, _audit_payload(row))
            keep.add(str(audit_path.resolve()).lower())
            result["audit_paths"].append(str(audit_path.resolve()))
        for target in _target_dirs(output_root, delivery_root, job_id):
            target = target.resolve()
            if not any(_inside(target, root) for root in allowed_roots):
                result["skipped"].append(f"Outside allowed roots: {target}")
                continue
            for file_path in _iter_files(target):
                resolved = file_path.resolve()
                key = str(resolved).lower()
                if key in keep:
                    continue
                if _inside(resolved, instagram_queue_root):
                    result["skipped"].append(f"Instagram queue path not deleted: {resolved}")
                    continue
                if _longvideos_path(resolved) and not allow_source_delete:
                    result["skipped"].append(f"Source video path not deleted: {resolved}")
                    continue
                if _report_path(resolved) and not cleanup_reports:
                    result["skipped"].append(f"Report/audit path not deleted: {resolved}")
                    continue
                result["planned_delete"].append(str(resolved))

    if mode == "dry_run" or not result["ok"]:
        _write_json(cleanup_summary_path, result)
        return result

    for value in result["planned_delete"]:
        path = Path(value)
        try:
            path.unlink()
            result["deleted"].append(value)
        except FileNotFoundError:
            pass
        except OSError as exc:
            result["ok"] = False
            result["errors"].append(f"{path}: {exc}")

    for row in rows:
        for target in sorted(_target_dirs(output_root, delivery_root, str(row.get("job_id") or "")), key=lambda p: len(p.parts), reverse=True):
            while target.exists() and target.is_dir() and not any(target == root for root in allowed_roots):
                try:
                    target.rmdir()
                except OSError:
                    break
                target = target.parent

    _write_json(cleanup_summary_path, result)
    return result
