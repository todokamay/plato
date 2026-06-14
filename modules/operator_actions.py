from __future__ import annotations

import os
from pathlib import Path

from config import project_path
from modules.batch_qc import scan_video_files
from modules.job_runner import operator_state, start_job, stop_running_watch
from modules.queue_engine import queue_stats
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
        "suggested": suggested_empty_state(),
    }
