from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from config import VIDEOAUTOPIPELINE_OUTPUT_ROOT, VIDEOAUTOPIPELINE_ROOT, project_path
from modules.batch_qc import scan_video_files
from modules.delivery_decision_explainer import explain_delivery_row
from modules.instagram_queue import get_stats as instagram_queue_stats
from modules.instagram_publisher import latest_publish_result
from modules.job_runner import DEFAULT_JOB_FILE, list_jobs, operator_state, start_job, stop_running_watch
from modules.queue_engine import queue_stats
from modules.replace_diagnostics import replace_diagnostics
from modules.rerender_requests import get_rerender_stats, list_rerender_requests, rerender_root
from modules.videoautopipeline_contract import default_delivery_root, find_waiting_jobs
from modules.videoautopipeline_detector import detect_videoautopipeline_outputs


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


def _resolve_path(value: str | Path | None, default: Path | None = None) -> Path:
    raw_value = str(value or "").strip().strip('"')
    raw = Path(raw_value) if raw_value else Path(default or "")
    if not raw.is_absolute():
        raw = project_path(raw)
    return raw.resolve()


def validate_videoautopipeline_root(root: str | Path | None = None) -> dict:
    path = _resolve_path(root, VIDEOAUTOPIPELINE_ROOT)
    reason = _unsafe_root_reason(path, "VideoAutoPipeline root")
    if reason:
        return {"ok": False, "vap_root": str(path), "error": reason}
    app_path = path / "app.py"
    if not app_path.exists() or not app_path.is_file():
        return {"ok": False, "vap_root": str(path), "error": f"VideoAutoPipeline app.py not found: {app_path}"}
    return {"ok": True, "vap_root": str(path)}


def validate_videoautopipeline_output_root(output_root: str | Path | None = None, *, must_exist: bool = False) -> dict:
    path = _resolve_path(output_root, VIDEOAUTOPIPELINE_OUTPUT_ROOT)
    reason = _unsafe_root_reason(path, "VideoAutoPipeline output root")
    if reason:
        return {"ok": False, "output_root": str(path), "error": reason}
    if must_exist and (not path.exists() or not path.is_dir()):
        return {"ok": False, "output_root": str(path), "error": f"Output root not found: {path}"}
    if path.exists() and not path.is_dir():
        return {"ok": False, "output_root": str(path), "error": "Output root exists but is not a directory."}
    return {"ok": True, "output_root": str(path)}


def validate_input_video(input_video: str | Path | None) -> dict:
    path = _resolve_path(input_video)
    if str(path) == str(_project_root()):
        return {"ok": False, "input_video": str(path), "error": "Project root is not a safe input video."}
    if path.parent == _drive_root(path):
        return {"ok": False, "input_video": str(path), "error": "Drive root is not a safe input video location."}
    if not path.exists() or not path.is_file() or path.suffix.lower() != ".mp4":
        return {"ok": False, "input_video": str(path), "error": f"Input MP4 not found: {path}"}
    return {"ok": True, "input_video": str(path)}


def _parse_limit(limit) -> dict:
    if limit is None or limit == "":
        return {"ok": True, "limit": None}
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Limit must be a positive integer."}
    if value <= 0:
        return {"ok": False, "error": "Limit must be a positive integer."}
    return {"ok": True, "limit": value}


def detect_outputs() -> dict:
    detection = detect_videoautopipeline_outputs(VIDEOAUTOPIPELINE_ROOT)
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


def start_vap_delivery_scan_job(folder: str | Path | None) -> dict:
    return _start_folder_job("vap_delivery_scan", folder)


def start_vap_delivery_process_job(folder: str | Path | None) -> dict:
    return _start_folder_job("vap_delivery_process", folder)


def start_vap_delivery_send_job(folder: str | Path | None) -> dict:
    return _start_folder_job("vap_delivery_send", folder)


def _longvideos_folder(vap_root: str | Path | None = None) -> Path:
    return _resolve_path(vap_root, VIDEOAUTOPIPELINE_ROOT).parent / "LongVideos"


def _latest_output_folder(output_root: str | Path | None = None) -> str:
    root = _resolve_path(output_root, VIDEOAUTOPIPELINE_OUTPUT_ROOT)
    if not root.exists() or not root.is_dir():
        return ""
    folders = [path for path in root.iterdir() if path.is_dir() and path.name not in {"batches", "jobs"}]
    return str(max(folders, key=lambda path: path.stat().st_mtime).resolve()) if folders else str(root)


def start_open_videoautopipeline_gui_job(vap_root: str | Path | None) -> dict:
    root = validate_videoautopipeline_root(vap_root)
    if not root["ok"]:
        return {"ok": False, "error": root["error"], "vap_root": root.get("vap_root")}
    job = start_job("open_videoautopipeline_gui", vap_root=root["vap_root"])
    return {"ok": True, "job": job, "vap_root": root["vap_root"]}


def start_vap_generate_longvideos_job(
    vap_root: str | Path | None,
    output_root: str | Path | None = None,
    limit=None,
) -> dict:
    return start_vap_batch_generate_folder_job(vap_root, _longvideos_folder(vap_root), output_root, limit)


def start_vap_generate_one_video_job(
    vap_root: str | Path | None,
    input_video: str | Path | None,
    output_root: str | Path | None = None,
) -> dict:
    return _start_vap_worker_action("vap_generate_one_video", vap_root, input_video, output_root)


def start_vap_batch_generate_folder_job(
    vap_root: str | Path | None,
    input_folder: str | Path | None,
    output_root: str | Path | None = None,
    limit=None,
) -> dict:
    return _start_vap_batch_action("vap_batch_generate_folder", vap_root, input_folder, output_root, limit)


def start_vap_batch_dry_run_job(
    vap_root: str | Path | None,
    input_folder: str | Path | None,
    output_root: str | Path | None = None,
    limit=None,
) -> dict:
    return _start_vap_batch_action("vap_batch_dry_run", vap_root, input_folder, output_root, limit)


def start_vap_resume_failed_job(
    vap_root: str | Path | None,
    output_root: str | Path | None = None,
    *,
    input_video: str | Path | None = None,
    input_folder: str | Path | None = None,
    limit=None,
) -> dict:
    root = validate_videoautopipeline_root(vap_root)
    if not root["ok"]:
        return {"ok": False, "error": root["error"], "vap_root": root.get("vap_root")}
    output = validate_videoautopipeline_output_root(output_root)
    if not output["ok"]:
        return {"ok": False, "error": output["error"], "output_root": output.get("output_root")}
    video = validate_input_video(input_video) if input_video else {"ok": True, "input_video": None}
    if not video["ok"]:
        return {"ok": False, "error": video["error"], "input_video": video.get("input_video")}
    folder = validate_operator_folder(input_folder) if not input_video else {"ok": True, "folder": None, "warnings": []}
    if not folder["ok"]:
        return {"ok": False, "error": folder["error"], "input_folder": folder.get("folder")}
    parsed = _parse_limit(limit)
    if not parsed["ok"]:
        return {"ok": False, "error": parsed["error"]}
    job = start_job(
        "vap_resume_failed",
        input_file=video["input_video"],
        input_folder=folder["folder"],
        output_root=output["output_root"],
        limit=parsed["limit"],
        vap_root=root["vap_root"],
    )
    return {"ok": True, "job": job, "vap_root": root["vap_root"], "output_root": output["output_root"], "warnings": folder.get("warnings", [])}


def start_vap_status_job(
    vap_root: str | Path | None,
    input_video: str | Path | None,
    output_root: str | Path | None = None,
) -> dict:
    if not str(input_video or "").strip():
        return vap_show_output_root(output_root)
    return _start_vap_worker_action("vap_status", vap_root, input_video, output_root)


def vap_show_output_root(output_root: str | Path | None = None) -> dict:
    output = validate_videoautopipeline_output_root(output_root)
    if not output["ok"]:
        return {"ok": False, "error": output["error"], "output_root": output.get("output_root")}
    latest = _latest_output_folder(output["output_root"])
    return {"ok": True, "output_root": output["output_root"], "latest_output_folder": latest, "message": latest or output["output_root"]}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _validate_rerender_request_path(path: str | Path | None = None) -> dict:
    value = str(path or "").strip().strip('"')
    if not value:
        latest = (list_rerender_requests("requested") or [{}])[0]
        value = latest.get("path") or ""
    if not value:
        return {"ok": False, "request_path": "", "error": "No requested rerender request found."}
    request_path = _resolve_path(value)
    root = rerender_root().resolve()
    if not _inside(request_path, root):
        return {"ok": False, "request_path": str(request_path), "error": "Rerender request path must be inside Plato rerender_requests."}
    if not request_path.exists() or not request_path.is_file() or request_path.suffix.lower() != ".json":
        return {"ok": False, "request_path": str(request_path), "error": f"Rerender request JSON not found: {request_path}"}
    return {"ok": True, "request_path": str(request_path)}


def _latest_vap_rerender_status(output_root: str | Path | None = None) -> str:
    output = _resolve_path(output_root, VIDEOAUTOPIPELINE_OUTPUT_ROOT)
    if not output.exists() or not output.is_dir():
        return ""
    candidates = [path for path in output.glob("*/rerender/*/status/*.json") if path.is_file()]
    return str(max(candidates, key=lambda path: path.stat().st_mtime).resolve()) if candidates else ""


def _validate_vap_rerender_status_path(path: str | Path | None = None, output_root: str | Path | None = None) -> dict:
    value = str(path or "").strip().strip('"') or _latest_vap_rerender_status(output_root)
    if not value:
        return {"ok": False, "status_path": "", "error": "No VideoAutoPipeline rerender status JSON found."}
    status_path = _resolve_path(value)
    output = _resolve_path(output_root, VIDEOAUTOPIPELINE_OUTPUT_ROOT)
    if not _inside(status_path, output):
        return {"ok": False, "status_path": str(status_path), "error": "Rerender status path must be inside VideoAutoPipeline output root."}
    if not status_path.exists() or not status_path.is_file() or status_path.suffix.lower() != ".json":
        return {"ok": False, "status_path": str(status_path), "error": f"Rerender status JSON not found: {status_path}"}
    return {"ok": True, "status_path": str(status_path)}


def start_vap_dry_run_rerender_request_job(
    vap_root: str | Path | None = None,
    request_path: str | Path | None = None,
    output_root: str | Path | None = None,
) -> dict:
    root = validate_videoautopipeline_root(vap_root)
    if not root["ok"]:
        return {"ok": False, "error": root["error"], "vap_root": root.get("vap_root")}
    output = validate_videoautopipeline_output_root(output_root)
    if not output["ok"]:
        return {"ok": False, "error": output["error"], "output_root": output.get("output_root")}
    request = _validate_rerender_request_path(request_path)
    if not request["ok"]:
        return {"ok": False, "error": request["error"], "request_path": request.get("request_path")}
    job = start_job("vap_dry_run_rerender_request", input_file=request["request_path"], output_root=output["output_root"], vap_root=root["vap_root"])
    return {"ok": True, "job": job, "request_path": request["request_path"], "output_root": output["output_root"], "vap_root": root["vap_root"]}


def start_import_rerender_result_job(
    status_path: str | Path | None = None,
    output_root: str | Path | None = None,
) -> dict:
    output = validate_videoautopipeline_output_root(output_root, must_exist=True)
    if not output["ok"]:
        return {"ok": False, "error": output["error"], "output_root": output.get("output_root")}
    status = _validate_vap_rerender_status_path(status_path, output["output_root"])
    if not status["ok"]:
        return {"ok": False, "error": status["error"], "status_path": status.get("status_path")}
    job = start_job("import_rerender_result", input_file=status["status_path"], output_root=output["output_root"])
    return {"ok": True, "job": job, "status_path": status["status_path"], "output_root": output["output_root"]}


def start_process_completed_rerenders_job(
    output_root: str | Path | None = None,
    *,
    dry_run: bool = True,
    auto_fix: bool = True,
    copy_results: bool = True,
    stop_after_approved=None,
) -> dict:
    output = validate_videoautopipeline_output_root(output_root, must_exist=True)
    if not output["ok"]:
        return {"ok": False, "error": output["error"], "output_root": output.get("output_root")}
    job = start_job(
        "process_completed_rerenders",
        output_root=output["output_root"],
        dry_run=bool(dry_run),
        auto_fix=bool(auto_fix),
        copy_results=bool(copy_results),
        send_telegram=False,
        stop_after_approved=3 if stop_after_approved in (None, "") else stop_after_approved,
    )
    return {"ok": True, "job": job, "output_root": output["output_root"]}


def start_repair_latest_rerender_request_job(
    vap_root: str | Path | None = None,
    output_root: str | Path | None = None,
    *,
    confirm_real_rerender: bool = False,
) -> dict:
    root = validate_videoautopipeline_root(vap_root)
    if not root["ok"]:
        return {"ok": False, "error": root["error"], "vap_root": root.get("vap_root")}
    output = validate_videoautopipeline_output_root(output_root)
    if not output["ok"]:
        return {"ok": False, "error": output["error"], "output_root": output.get("output_root")}
    request = _validate_rerender_request_path()
    if not request["ok"]:
        return {"ok": False, "error": request["error"], "request_path": request.get("request_path")}
    job = start_job(
        "repair_latest_rerender_request",
        output_root=output["output_root"],
        vap_root=root["vap_root"],
        confirm_real_rerender=bool(confirm_real_rerender),
    )
    return {
        "ok": True,
        "job": job,
        "request_path": request["request_path"],
        "output_root": output["output_root"],
        "vap_root": root["vap_root"],
        "message": "Rerender repair loop started.",
    }


def start_process_waiting_for_plato_job(
    output_root: str | Path | None = None,
    *,
    dry_run: bool = True,
    auto_fix: bool = True,
    copy_results: bool = True,
    stop_after_approved=None,
) -> dict:
    return start_process_videoautopipeline_outputs_job(
        output_root,
        dry_run=dry_run,
        auto_fix=auto_fix,
        copy_results=copy_results,
        stop_after_approved=stop_after_approved,
    )


def start_send_approved_to_telegram_job(output_root: str | Path | None = None) -> dict:
    return start_process_videoautopipeline_outputs_job(output_root, dry_run=False, auto_fix=True, copy_results=True, send_telegram=True)


def _start_vap_worker_action(
    action: str,
    vap_root: str | Path | None,
    input_video: str | Path | None,
    output_root: str | Path | None = None,
) -> dict:
    root = validate_videoautopipeline_root(vap_root)
    if not root["ok"]:
        return {"ok": False, "error": root["error"], "vap_root": root.get("vap_root")}
    video = validate_input_video(input_video)
    if not video["ok"]:
        return {"ok": False, "error": video["error"], "input_video": video.get("input_video")}
    output = validate_videoautopipeline_output_root(output_root)
    if not output["ok"]:
        return {"ok": False, "error": output["error"], "output_root": output.get("output_root")}
    job = start_job(action, input_file=video["input_video"], output_root=output["output_root"], vap_root=root["vap_root"])
    return {"ok": True, "job": job, "vap_root": root["vap_root"], "output_root": output["output_root"]}


def _start_vap_batch_action(
    action: str,
    vap_root: str | Path | None,
    input_folder: str | Path | None,
    output_root: str | Path | None = None,
    limit=None,
) -> dict:
    root = validate_videoautopipeline_root(vap_root)
    if not root["ok"]:
        return {"ok": False, "error": root["error"], "vap_root": root.get("vap_root")}
    folder = validate_operator_folder(input_folder)
    if not folder["ok"]:
        return {"ok": False, "error": folder["error"], "input_folder": folder.get("folder")}
    output = validate_videoautopipeline_output_root(output_root)
    if not output["ok"]:
        return {"ok": False, "error": output["error"], "output_root": output.get("output_root")}
    parsed = _parse_limit(limit)
    if not parsed["ok"]:
        return {"ok": False, "error": parsed["error"]}
    job = start_job(
        action,
        input_folder=folder["folder"],
        output_root=output["output_root"],
        limit=parsed["limit"],
        vap_root=root["vap_root"],
    )
    return {"ok": True, "job": job, "vap_root": root["vap_root"], "output_root": output["output_root"], "warnings": folder.get("warnings", [])}


def start_videoautopipeline_worker_job(
    vap_root: str | Path | None,
    input_video: str | Path | None,
    output_root: str | Path | None = None,
) -> dict:
    root = validate_videoautopipeline_root(vap_root)
    if not root["ok"]:
        return {"ok": False, "error": root["error"], "vap_root": root.get("vap_root")}
    video = validate_input_video(input_video)
    if not video["ok"]:
        return {"ok": False, "error": video["error"], "input_video": video.get("input_video")}
    output = validate_videoautopipeline_output_root(output_root)
    if not output["ok"]:
        return {"ok": False, "error": output["error"], "output_root": output.get("output_root")}
    job = start_job(
        "run_videoautopipeline_worker",
        input_file=video["input_video"],
        output_root=output["output_root"],
        vap_root=root["vap_root"],
    )
    return {"ok": True, "job": job, "vap_root": root["vap_root"], "output_root": output["output_root"]}


def start_videoautopipeline_batch_job(
    vap_root: str | Path | None,
    input_folder: str | Path | None,
    output_root: str | Path | None = None,
    limit=None,
) -> dict:
    root = validate_videoautopipeline_root(vap_root)
    if not root["ok"]:
        return {"ok": False, "error": root["error"], "vap_root": root.get("vap_root")}
    folder = validate_operator_folder(input_folder)
    if not folder["ok"]:
        return {"ok": False, "error": folder["error"], "input_folder": folder.get("folder")}
    output = validate_videoautopipeline_output_root(output_root)
    if not output["ok"]:
        return {"ok": False, "error": output["error"], "output_root": output.get("output_root")}
    parsed = _parse_limit(limit)
    if not parsed["ok"]:
        return {"ok": False, "error": parsed["error"]}
    job = start_job(
        "run_videoautopipeline_batch",
        input_folder=folder["folder"],
        output_root=output["output_root"],
        limit=parsed["limit"],
        vap_root=root["vap_root"],
    )
    return {"ok": True, "job": job, "vap_root": root["vap_root"], "output_root": output["output_root"], "warnings": folder.get("warnings", [])}


def start_process_videoautopipeline_outputs_job(
    output_root: str | Path | None = None,
    *,
    dry_run: bool = True,
    auto_fix: bool = True,
    copy_results: bool = True,
    send_telegram: bool = False,
    stop_after_approved=None,
) -> dict:
    output = validate_videoautopipeline_output_root(output_root, must_exist=True)
    if not output["ok"]:
        return {"ok": False, "error": output["error"], "output_root": output.get("output_root")}
    job = start_job(
        "process_videoautopipeline_outputs",
        output_root=output["output_root"],
        dry_run=bool(dry_run),
        auto_fix=bool(auto_fix),
        copy_results=bool(copy_results),
        send_telegram=bool(send_telegram),
        stop_after_approved=3 if stop_after_approved in (None, "") else stop_after_approved,
    )
    return {"ok": True, "job": job, "output_root": output["output_root"]}


def start_full_videoautopipeline_flow_job(
    vap_root: str | Path | None,
    output_root: str | Path | None,
    *,
    input_video: str | Path | None = None,
    input_folder: str | Path | None = None,
    limit=None,
    dry_run: bool = True,
    auto_fix: bool = True,
    copy_results: bool = True,
    send_telegram: bool = False,
    davinci_mode: str = "required",
    cleanup_mode: str = "keep_all",
    factory_preset: str = "quality",
    max_candidates=None,
    top_render_count=None,
    stop_after_approved=None,
    whisper_model: str = "medium",
    confirm_cleanup: bool = False,
) -> dict:
    root = validate_videoautopipeline_root(vap_root)
    if not root["ok"]:
        return {"ok": False, "error": root["error"], "vap_root": root.get("vap_root")}
    output = validate_videoautopipeline_output_root(output_root)
    if not output["ok"]:
        return {"ok": False, "error": output["error"], "output_root": output.get("output_root")}
    video = validate_input_video(input_video) if input_video else {"ok": True, "input_video": None}
    if not video["ok"]:
        return {"ok": False, "error": video["error"], "input_video": video.get("input_video")}
    folder = validate_operator_folder(input_folder) if not input_video else {"ok": True, "folder": None, "warnings": []}
    if not folder["ok"]:
        return {"ok": False, "error": folder["error"], "input_folder": folder.get("folder")}
    parsed = _parse_limit(limit)
    if not parsed["ok"]:
        return {"ok": False, "error": parsed["error"]}
    job = start_job(
        "run_full_videoautopipeline_to_plato_flow",
        input_file=video["input_video"],
        input_folder=folder["folder"],
        output_root=output["output_root"],
        limit=parsed["limit"],
        dry_run=bool(dry_run),
        auto_fix=bool(auto_fix),
        copy_results=bool(copy_results),
        send_telegram=bool(send_telegram),
        vap_root=root["vap_root"],
        davinci_mode=davinci_mode if davinci_mode in {"required", "optional", "disabled"} else "required",
        cleanup_mode=cleanup_mode if cleanup_mode in {"keep_final_only", "keep_all", "dry_run"} else "keep_all",
        factory_preset=factory_preset or "quality",
        max_candidates=12 if max_candidates in (None, "") else max_candidates,
        top_render_count=6 if top_render_count in (None, "") else top_render_count,
        stop_after_approved=3 if stop_after_approved in (None, "") else stop_after_approved,
        whisper_model=whisper_model or "medium",
        confirm_cleanup=bool(confirm_cleanup),
    )
    return {"ok": True, "job": job, "vap_root": root["vap_root"], "output_root": output["output_root"], "warnings": folder.get("warnings", [])}


FULL_FLOW_ACTION = "run_full_videoautopipeline_to_plato_flow"
FULL_SUMMARY_PREFIX = "FULL_PIPELINE_SUMMARY "
FULL_STEP_ORDER = [
    "video_generation",
    "davinci",
    "plato_analysis",
    "plato_improvement",
    "reanalysis",
    "delivery",
    "cleanup",
]
VAP_JOB_TYPES = {
    "open_videoautopipeline_gui",
    "run_videoautopipeline_worker",
    "run_videoautopipeline_batch",
    FULL_FLOW_ACTION,
    "vap_generate_longvideos",
    "vap_generate_one_video",
    "vap_batch_generate_folder",
    "vap_batch_dry_run",
    "vap_resume_failed",
    "vap_status",
    "repair_latest_rerender_request",
}


def _read_json_file(path: str | Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _duration_seconds(job: dict) -> int | None:
    start = _parse_time(job.get("started_at") or job.get("created_at"))
    if not start:
        return None
    end = _parse_time(job.get("finished_at")) or datetime.now(timezone.utc)
    return max(0, int((end - start).total_seconds()))


def _latest_line(job: dict | None) -> str:
    if not job:
        return ""
    summary = job.get("result_summary") or {}
    if summary.get("last_line"):
        return str(summary["last_line"])
    for key in ("stderr_tail", "stdout_tail"):
        for line in reversed(str(job.get(key) or "").splitlines()):
            if line.strip():
                return line.strip()
    return ""


def _full_summary(job: dict | None) -> dict:
    if not job:
        return {}
    for line in reversed(str(job.get("stdout_tail") or "").splitlines()):
        if not line.startswith(FULL_SUMMARY_PREFIX):
            continue
        try:
            data = json.loads(line.replace(FULL_SUMMARY_PREFIX, "", 1))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def _step_reason(summary: dict, step_name: str) -> str:
    step = (summary.get("steps") or {}).get(step_name) or {}
    return str(step.get("reason") or step.get("error") or step.get("telegram_status") or "")


def _current_stage(job: dict | None, summary: dict) -> str:
    if not job:
        return "none"
    if summary.get("failed_step"):
        return str(summary["failed_step"])
    if summary.get("overall_status") == "succeeded" or job.get("status") == "completed":
        return "succeeded"
    steps = summary.get("steps") or {}
    for name in FULL_STEP_ORDER:
        status = (steps.get(name) or {}).get("status")
        if status in {"running", "started", "pending", "planned"}:
            return name
    return str(job.get("status") or "idle")


def _arg_value(args: list, flag: str) -> str:
    try:
        index = list(args).index(flag)
    except ValueError:
        return ""
    if index + 1 >= len(args):
        return ""
    return str(args[index + 1])


def _job_input_path(job: dict | None) -> str:
    if not job:
        return ""
    args = job.get("args") or []
    return _arg_value(args, "--input-video") or _arg_value(args, "--input-folder") or _arg_value(args, "--worker") or _arg_value(args, "--batch")


def _delivery_row(delivery_summary: dict) -> dict:
    jobs = delivery_summary.get("jobs") or []
    return jobs[0] if jobs and isinstance(jobs[0], dict) else {}


def _job_display_status(job: dict | None) -> str:
    if not job:
        return "none"
    if job.get("status") == "running":
        return "running"
    if job.get("status") == "failed":
        return "failed"
    if job.get("status") == "completed":
        return "succeeded"
    return str(job.get("status") or "none")


def _videoautopipeline_bar(jobs: list[dict]) -> str:
    job = _latest_job(jobs, VAP_JOB_TYPES)
    if not job:
        return "idle"
    return _job_display_status(job).replace("none", "idle")


def _plato_bar(job: dict | None, summary: dict, delivery: dict) -> str:
    stage = _current_stage(job, summary)
    if job and job.get("status") == "running":
        if stage == "plato_analysis":
            return "analyzing"
        if stage in {"plato_improvement", "reanalysis"}:
            return "fixing"
    if delivery.get("approved_output_path") or delivery.get("delivery_status") in {"ready", "sent"}:
        return "approved"
    if delivery.get("plato_status") == "rejected" or delivery.get("delivery_status") == "not_sent":
        return "rejected"
    return "idle"


def _telegram_bar(delivery_summary: dict, delivery: dict, summary: dict) -> str:
    telegram_status = str(delivery.get("telegram_status") or "")
    if delivery_summary.get("dry_run") or ((summary.get("steps") or {}).get("delivery") or {}).get("status") == "dry_run":
        return "dry-run"
    if telegram_status == "sent" or delivery.get("sent"):
        return "sent"
    if telegram_status.startswith("skipped"):
        return "skipped"
    if delivery.get("approved_output_path"):
        return "ready"
    return "disabled"


def control_room_status(
    job_file: str | Path = DEFAULT_JOB_FILE,
    delivery_summary_path: str | Path | None = None,
) -> dict:
    jobs = list_jobs(limit=20, job_file=job_file)
    current = next((job for job in jobs if job.get("status") == "running"), None)
    latest_full = _latest_job(jobs, {FULL_FLOW_ACTION})
    display_job = current or latest_full or (jobs[0] if jobs else None)
    summary = _full_summary(display_job) or _full_summary(latest_full)
    failed_step = str(summary.get("failed_step") or "")
    reason = _step_reason(summary, failed_step) if failed_step else ""
    if not reason:
        reason = _latest_line(display_job) if display_job and display_job.get("status") == "failed" else ""

    delivery_path = Path(delivery_summary_path) if delivery_summary_path else default_delivery_root() / "delivery_summary.json"
    delivery_summary = _read_json_file(delivery_path)
    delivery = _delivery_row(delivery_summary)
    delivery_explanation = explain_delivery_row(delivery, delivery_path)
    approved_output = str(delivery.get("approved_output_path") or "")
    final_reason = str(delivery.get("reason") or delivery.get("improvement_reason") or reason or "")

    history = []
    for job in jobs[:20]:
        history.append(
            {
                "created_at": job.get("created_at") or "",
                "action": job.get("job_type") or "",
                "status": job.get("status") or "",
                "return_code": job.get("exit_code"),
                "duration_seconds": _duration_seconds(job),
                "latest_line": _latest_line(job),
                "job_id": job.get("job_id") or "",
                "command": job.get("command") or "",
            }
        )

    return {
        "ok": True,
        "status_bar": {
            "videoautopipeline": _videoautopipeline_bar(jobs),
            "plato": _plato_bar(display_job, summary, delivery),
            "telegram": _telegram_bar(delivery_summary, delivery, summary),
            "current_job": _job_display_status(display_job),
        },
        "current_run": {
            "job_id": display_job.get("job_id") if display_job else "",
            "input_path": _job_input_path(display_job),
            "current_stage": _current_stage(display_job, summary),
            "elapsed_seconds": _duration_seconds(display_job) if display_job else None,
            "latest_heartbeat": (display_job or {}).get("finished_at") or (display_job or {}).get("started_at") or (display_job or {}).get("created_at") or "",
            "stdout_tail": (display_job or {}).get("stdout_tail") or "",
            "stderr_tail": (display_job or {}).get("stderr_tail") or "",
            "failed_step": failed_step,
            "reason": reason,
            "empty": display_job is None,
        },
        "final_output": {
            "approved_output_path": approved_output,
            "source_final_path": str(delivery.get("source_final_path") or ""),
            "plato_score": delivery.get("plato_score") if delivery else "",
            "plato_verdict": str(delivery.get("plato_verdict") or ""),
            "plato_bucket": str(delivery.get("plato_bucket") or ""),
            "delivery_status": str(delivery.get("delivery_status") or ""),
            "telegram_status": str(delivery.get("telegram_status") or ""),
            "reason": final_reason,
            "blocker_route": str(delivery.get("blocker_route") or ""),
            "blocker_fix_attempted": bool(delivery.get("blocker_fix_attempted")),
            "blocker_fix_accepted": bool(delivery.get("blocker_fix_accepted")),
            "blocker_fixed_output_path": str(delivery.get("blocker_fixed_output_path") or ""),
            "blocker_next_action": str(delivery.get("blocker_next_action") or ""),
            "message": "No approved output yet" if not approved_output else "",
            "delivery_summary_path": str(delivery_path) if delivery_path.exists() else "",
            "explanation": delivery_explanation,
        },
        "instagram_queue": {**instagram_queue_stats(), "latest_publish_result": latest_publish_result()},
        "rerender_requests": get_rerender_stats(),
        "job_history": history,
    }


def _retry_base_from_latest_full() -> dict:
    latest = _latest_job(list_jobs(limit=100), {FULL_FLOW_ACTION})
    if not latest:
        return {}
    args = latest.get("args") or []
    return {
        "vap_root": _arg_value(args, "--vap-root"),
        "output_root": _arg_value(args, "--output-root"),
        "input_video": _arg_value(args, "--input-video"),
        "input_folder": _arg_value(args, "--input-folder"),
        "limit": _arg_value(args, "--limit"),
        "dry_run": "--dry-run" in args,
        "auto_fix": "--auto-fix" in args,
        "copy_results": "--copy-results" in args,
        "send_telegram": "--send-telegram" in args,
        "davinci_mode": _arg_value(args, "--davinci-mode") or "required",
        "cleanup_mode": _arg_value(args, "--cleanup-mode") or "keep_all",
        "confirm_cleanup": "--confirm-cleanup" in args,
        "factory_preset": _arg_value(args, "--factory-preset") or "quality",
        "max_candidates": _arg_value(args, "--max-candidates") or "12",
        "top_render_count": _arg_value(args, "--top-render-count") or "6",
        "stop_after_approved": _arg_value(args, "--stop-after-approved") or "3",
        "whisper_model": _arg_value(args, "--whisper-model") or "medium",
    }


def _payload_text(data: dict, key: str, default: str = "") -> str:
    return str(data.get(key) or default or "").strip()


def _payload_bool(data: dict, key: str, default: bool) -> bool:
    return bool(data[key]) if key in data else default


def _payload_value(data: dict, key: str, default):
    value = data.get(key)
    return default if value is None or value == "" else value


def start_retry_full_pipeline_job(data: dict | None = None) -> dict:
    data = data or {}
    base = _retry_base_from_latest_full()
    if not base and not (_payload_text(data, "input_video") or _payload_text(data, "input_folder")):
        return {"ok": False, "error": "No previous full pipeline job found to retry."}
    return start_full_videoautopipeline_flow_job(
        _payload_text(data, "vap_root", base.get("vap_root") or str(VIDEOAUTOPIPELINE_ROOT)),
        _payload_text(data, "output_root", base.get("output_root") or str(VIDEOAUTOPIPELINE_OUTPUT_ROOT)),
        input_video=_payload_text(data, "input_video", base.get("input_video", "")),
        input_folder=_payload_text(data, "input_folder", base.get("input_folder", "")),
        limit=data.get("limit") or base.get("limit"),
        dry_run=_payload_bool(data, "dry_run", True),
        auto_fix=_payload_bool(data, "auto_fix", base.get("auto_fix", True)),
        copy_results=_payload_bool(data, "copy_results", base.get("copy_results", True)),
        send_telegram=_payload_bool(data, "send_telegram", base.get("send_telegram", False)),
        davinci_mode=_payload_text(data, "davinci_mode", base.get("davinci_mode", "required")) or "required",
        cleanup_mode=_payload_text(data, "cleanup_mode", base.get("cleanup_mode", "keep_all")) or "keep_all",
        confirm_cleanup=_payload_bool(data, "confirm_cleanup", base.get("confirm_cleanup", False)),
        factory_preset=_payload_text(data, "factory_preset", base.get("factory_preset", "quality")) or "quality",
        max_candidates=_payload_value(data, "max_candidates", base.get("max_candidates") or 12),
        top_render_count=_payload_value(data, "top_render_count", base.get("top_render_count") or 6),
        stop_after_approved=_payload_value(data, "stop_after_approved", base.get("stop_after_approved") or 3),
        whisper_model=_payload_text(data, "whisper_model", base.get("whisper_model", "medium")) or "medium",
    )


def start_retry_plato_only_job(data: dict | None = None) -> dict:
    data = data or {}
    return start_process_waiting_for_plato_job(
        _payload_text(data, "output_root", str(VIDEOAUTOPIPELINE_OUTPUT_ROOT)),
        dry_run=_payload_bool(data, "dry_run", True),
        auto_fix=_payload_bool(data, "auto_fix", True),
        copy_results=_payload_bool(data, "copy_results", True),
        stop_after_approved=_payload_value(data, "stop_after_approved", 3),
    )


def start_retry_delivery_only_job(data: dict | None = None) -> dict:
    data = data or {}
    return start_process_videoautopipeline_outputs_job(
        _payload_text(data, "output_root", str(VIDEOAUTOPIPELINE_OUTPUT_ROOT)),
        dry_run=_payload_bool(data, "dry_run", True),
        auto_fix=_payload_bool(data, "auto_fix", True),
        copy_results=_payload_bool(data, "copy_results", True),
        send_telegram=_payload_bool(data, "send_telegram", False),
        stop_after_approved=_payload_value(data, "stop_after_approved", 3),
    )


def start_watch_job(folder: str | Path | None) -> dict:
    return _start_folder_job("start_watch_mode", folder)


def stop_watch_job() -> dict:
    return stop_running_watch()


def _latest_job(jobs: list[dict], types: set[str]) -> dict | None:
    return next((job for job in jobs if job.get("job_type") in types), None)


def videoautopipeline_status(jobs: list[dict]) -> dict:
    output_root = VIDEOAUTOPIPELINE_OUTPUT_ROOT
    delivery_summary = default_delivery_root() / "delivery_summary.json"
    try:
        waiting_count = len(find_waiting_jobs(output_root))
    except Exception:
        waiting_count = 0
    return {
        "root": str(VIDEOAUTOPIPELINE_ROOT),
        "output_root": str(output_root),
        "latest_output_folder": _latest_output_folder(output_root),
        "waiting_for_plato_count": waiting_count,
        "latest_videoautopipeline_job": _latest_job(jobs, {"open_videoautopipeline_gui", "run_videoautopipeline_worker", "run_videoautopipeline_batch", "run_full_videoautopipeline_to_plato_flow", "vap_generate_longvideos", "vap_generate_one_video", "vap_batch_generate_folder", "vap_batch_dry_run", "vap_resume_failed", "vap_status", "repair_latest_rerender_request"}),
        "latest_plato_processing_job": _latest_job(jobs, {"process_videoautopipeline_outputs", "vap_delivery_scan", "vap_delivery_process", "vap_delivery_send"}),
        "last_delivery_summary_path": str(delivery_summary) if delivery_summary.exists() else "",
    }


def operator_status() -> dict:
    state = operator_state()
    return {
        "ok": True,
        "detection": detect_outputs(),
        "jobs": state,
        "queue": queue_stats(),
        "replace": replace_diagnostics(),
        "videoautopipeline": videoautopipeline_status(state.get("jobs", [])),
        "suggested": suggested_empty_state(),
    }
