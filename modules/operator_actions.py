from __future__ import annotations

import os
from pathlib import Path

from config import VIDEOAUTOPIPELINE_OUTPUT_ROOT, VIDEOAUTOPIPELINE_ROOT, project_path
from modules.batch_qc import scan_video_files
from modules.job_runner import operator_state, start_job, stop_running_watch
from modules.queue_engine import queue_stats
from modules.replace_diagnostics import replace_diagnostics
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
    )
    return {"ok": True, "job": job, "vap_root": root["vap_root"], "output_root": output["output_root"], "warnings": folder.get("warnings", [])}


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
        "waiting_for_plato_count": waiting_count,
        "latest_videoautopipeline_job": _latest_job(jobs, {"run_videoautopipeline_worker", "run_videoautopipeline_batch", "run_full_videoautopipeline_to_plato_flow"}),
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
