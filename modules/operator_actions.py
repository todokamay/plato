from __future__ import annotations

import os
from pathlib import Path

from config import project_path
from modules.batch_qc import scan_video_files
from modules.job_runner import operator_state, start_job, stop_running_watch
from modules.queue_engine import queue_stats
from modules.replace_diagnostics import replace_diagnostics
from modules.videoautopipeline_detector import DEFAULT_VIDEOAUTOPIPELINE_ROOT, detect_videoautopipeline_outputs


MANUAL_FOLDER = project_path("data/temp/manual_videoautopipeline_outputs")
SUGGESTED_MANUAL_PATH = r"data\temp\manual_videoautopipeline_outputs"


def suggested_empty_state() -> dict:
    return {
        "message": "No output folder found yet.",
        "next_steps": [
            r"Create data\temp\manual_videoautopipeline_outputs",
            "Put one or more .mp4 files inside.",
            r"Use manual folder path: data\temp\manual_videoautopipeline_outputs",
        ],
        "manual_folder": SUGGESTED_MANUAL_PATH,
    }


def _project_root() -> Path:
    return project_path(".").resolve()


def _user_home() -> Path:
    return Path.home().resolve()


def _drive_root(path: Path) -> Path:
    anchor = path.anchor or "\\"
    return Path(anchor).resolve()


def resolve_operator_folder(folder: str | Path | None) -> Path:
    value = str(folder or "").strip().strip('"')
    if not value:
        raise ValueError("Folder path is empty. Enter a folder path or run detection first.")
    raw = Path(value)
    if not raw.is_absolute():
        raw = project_path(raw)
    return raw.resolve()


def validate_operator_folder(folder: str | Path | None) -> dict:
    try:
        path = resolve_operator_folder(folder)
    except ValueError as exc:
        return {"ok": False, "folder": "", "error": str(exc)}
    project_root = _project_root()
    dangerous = {
        str(project_root).lower(): "Project root is not a safe input folder.",
        str(_user_home()).lower(): "User home root is too broad for an input folder.",
        str(_drive_root(path)).lower(): "Drive root is not a safe input folder.",
    }
    system_roots = [
        os.environ.get("SystemRoot"),
        os.environ.get("WINDIR"),
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    ]
    for root in system_roots:
        if root:
            dangerous[str(Path(root).resolve()).lower()] = "Windows/system folders are not safe input folders."
    reason = dangerous.get(str(path).lower())
    if reason:
        return {"ok": False, "folder": str(path), "error": reason}
    if not path.exists() or not path.is_dir():
        return {"ok": False, "folder": str(path), "error": f"Folder not found: {path}"}
    mp4s = [item for item in path.iterdir() if item.is_file() and item.suffix.lower() == ".mp4"]
    videos = scan_video_files(path)
    warnings = []
    if not mp4s:
        warnings.append("No .mp4 files found in this folder yet.")
    if not videos:
        warnings.append("No supported video files found in this folder yet.")
    return {"ok": True, "folder": str(path), "mp4_count": len(mp4s), "video_count": len(videos), "warnings": warnings}


def _unsafe_root_reason(path: Path, label: str) -> str:
    project_root = _project_root()
    dangerous = {
        str(project_root).lower(): f"Project root is not a safe {label}.",
        str(_user_home()).lower(): f"User home root is too broad for a {label}.",
        str(_drive_root(path)).lower(): f"Drive root is not a safe {label}.",
    }
    system_roots = [
        os.environ.get("SystemRoot"),
        os.environ.get("WINDIR"),
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    ]
    for root in system_roots:
        if root:
            dangerous[str(Path(root).resolve()).lower()] = f"Windows/system folders are not a safe {label}."
    return dangerous.get(str(path).lower(), "")


def validate_backup_dir(backup_dir: str | Path | None, input_folder: str | Path | None = None) -> dict:
    value = str(backup_dir or "").strip().strip('"')
    if not value:
        return {"ok": False, "backup_dir": "", "error": "Backup directory is required."}
    raw = Path(value)
    if not raw.is_absolute():
        raw = project_path(raw)
    path = raw.resolve()
    reason = _unsafe_root_reason(path, "backup directory")
    if reason:
        return {"ok": False, "backup_dir": str(path), "error": reason}
    if path.exists() and not path.is_dir():
        return {"ok": False, "backup_dir": str(path), "error": "Backup path exists but is not a directory."}
    if input_folder:
        source = resolve_operator_folder(input_folder)
        if path == source:
            return {"ok": False, "backup_dir": str(path), "error": "Backup directory cannot be the input folder."}
    return {"ok": True, "backup_dir": str(path)}


def validate_replace_log(log_path: str | Path | None) -> dict:
    value = str(log_path or "").strip().strip('"')
    if not value:
        return {"ok": False, "log_path": "", "error": "Replace log path is required."}
    raw = Path(value)
    if not raw.is_absolute():
        raw = project_path(raw)
    path = raw.resolve()
    if path.name != "replace_log.json":
        return {"ok": False, "log_path": str(path), "error": "Rollback requires a replace_log.json file."}
    if not path.exists() or not path.is_file():
        return {"ok": False, "log_path": str(path), "error": f"Replace log not found: {path}"}
    return {"ok": True, "log_path": str(path)}


def detect_outputs() -> dict:
    detection = detect_videoautopipeline_outputs(DEFAULT_VIDEOAUTOPIPELINE_ROOT)
    if not detection.get("found"):
        detection["empty_state"] = suggested_empty_state()
    return detection


def _start_folder_job(action: str, folder: str | Path | None) -> dict:
    validation = validate_operator_folder(folder)
    if not validation["ok"]:
        return {"ok": False, "error": validation["error"], "folder": validation.get("folder"), "suggested": suggested_empty_state()}
    job = start_job(action, folder=validation["folder"])
    return {"ok": True, "job": job, "folder": validation["folder"], "warnings": validation.get("warnings", [])}


def start_detect_job() -> dict:
    job = start_job("detect_outputs")
    return {"ok": True, "job": job, "detection": detect_outputs()}


def start_dry_run_job() -> dict:
    return {"ok": True, "job": start_job("dry_run_orchestrator")}


def start_auto_qc_job(folder: str | Path | None) -> dict:
    return _start_folder_job("run_auto_qc_once", folder)


def start_auto_qc_replace_job(
    folder: str | Path | None,
    backup_dir: str | Path | None,
    *,
    replace_enabled: bool = False,
    replace_confirmed: bool = False,
) -> dict:
    if not replace_enabled or not replace_confirmed:
        return {"ok": False, "error": "Safe Replace requires both explicit checkboxes."}
    validation = validate_operator_folder(folder)
    if not validation["ok"]:
        return {"ok": False, "error": validation["error"], "folder": validation.get("folder"), "suggested": suggested_empty_state()}
    backup = validate_backup_dir(backup_dir, validation["folder"])
    if not backup["ok"]:
        return {"ok": False, "error": backup["error"], "backup_dir": backup.get("backup_dir")}
    job = start_job("auto_qc_replace_once", folder=validation["folder"], backup_dir=backup["backup_dir"])
    return {"ok": True, "job": job, "folder": validation["folder"], "backup_dir": backup["backup_dir"], "warnings": validation.get("warnings", [])}


def start_replace_rollback_job(log_path: str | Path | None) -> dict:
    validation = validate_replace_log(log_path)
    if not validation["ok"]:
        return {"ok": False, "error": validation["error"], "log_path": validation.get("log_path")}
    return {"ok": True, "job": start_job("rollback_replace_log", log_path=validation["log_path"]), "log_path": validation["log_path"]}


def start_production_diagnostics_job() -> dict:
    return {"ok": True, "job": start_job("export_production_diagnostics")}


def start_batch_qc_job(folder: str | Path | None) -> dict:
    return _start_folder_job("run_batch_qc_once", folder)


def start_watch_job(folder: str | Path | None) -> dict:
    return _start_folder_job("start_watch_mode", folder)


def stop_watch_job() -> dict:
    return stop_running_watch()


def operator_status() -> dict:
    state = operator_state()
    return {
        "ok": True,
        "detection": detect_outputs(),
        "jobs": state,
        "queue": queue_stats(),
        "replace": replace_diagnostics(),
        "suggested": suggested_empty_state(),
    }
