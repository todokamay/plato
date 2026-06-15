from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import project_path


JOB_STATUSES = {"queued", "running", "completed", "failed", "cancelled"}
DEFAULT_JOB_FILE = project_path("data/jobs/jobs.json")
TAIL_LIMIT = 8000

ACTION_DEFINITIONS = {
    "detect_outputs": {
        "display": r"py tools\detect_videoautopipeline_outputs.py --json",
        "args": ["tools/detect_videoautopipeline_outputs.py", "--json"],
        "requires_folder": False,
        "cancellable": False,
    },
    "dry_run_orchestrator": {
        "display": r"py tools\run_orchestrator.py --once --dry-run --json",
        "args": ["tools/run_orchestrator.py", "--once", "--dry-run", "--json"],
        "requires_folder": False,
        "cancellable": False,
    },
    "run_auto_qc_once": {
        "display": r"py tools\auto_qc_fix_folder.py SELECTED_FOLDER --auto-fix --copy-results --allow-original-short --short-clip-min-duration 5",
        "args": [
            "tools/auto_qc_fix_folder.py",
            "{folder}",
            "--auto-fix",
            "--copy-results",
            "--allow-original-short",
            "--short-clip-min-duration",
            "5",
        ],
        "requires_folder": True,
        "cancellable": False,
    },
    "auto_qc_replace_once": {
        "display": r"py tools\auto_qc_fix_folder.py SELECTED_FOLDER --auto-fix --copy-results --allow-original-short --replace-with-fixed --confirm-replace --backup-dir BACKUP_DIR",
        "args": [
            "tools/auto_qc_fix_folder.py",
            "{folder}",
            "--auto-fix",
            "--copy-results",
            "--allow-original-short",
            "--replace-with-fixed",
            "--confirm-replace",
            "--backup-dir",
            "{backup_dir}",
        ],
        "requires_folder": True,
        "requires_backup_dir": True,
        "cancellable": False,
    },
    "rollback_replace_log": {
        "display": r"py tools\auto_qc_fix_folder.py --rollback-replace-log LOG_PATH",
        "args": ["tools/auto_qc_fix_folder.py", "--rollback-replace-log", "{log_path}"],
        "requires_folder": False,
        "requires_log_path": True,
        "cancellable": False,
    },
    "export_production_diagnostics": {
        "display": r"py tools\export_production_diagnostics.py",
        "args": ["tools/export_production_diagnostics.py"],
        "requires_folder": False,
        "cancellable": False,
    },
    "start_watch_mode": {
        "display": r"py tools\watch_videoautopipeline_outputs.py SELECTED_FOLDER --auto-fix --copy-results --allow-original-short --short-clip-min-duration 5",
        "args": [
            "tools/watch_videoautopipeline_outputs.py",
            "{folder}",
            "--auto-fix",
            "--copy-results",
            "--allow-original-short",
            "--short-clip-min-duration",
            "5",
        ],
        "requires_folder": True,
        "cancellable": True,
        "singleton": True,
    },
    "run_batch_qc_once": {
        "display": r"py tools\batch_qc_folder.py SELECTED_FOLDER --copy-results",
        "args": ["tools/batch_qc_folder.py", "{folder}", "--copy-results"],
        "requires_folder": True,
        "cancellable": False,
    },
}

_PROCESSES: dict[str, subprocess.Popen] = {}
_LOCK = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_state() -> dict:
    return {"version": 1, "updated_at": utc_now(), "jobs": []}


def load_jobs(job_file: str | Path = DEFAULT_JOB_FILE) -> dict:
    path = Path(job_file)
    if not path.exists():
        return _empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_state()
    if not isinstance(data, dict):
        return _empty_state()
    data.setdefault("version", 1)
    data.setdefault("jobs", [])
    return data


def save_jobs(state: dict, job_file: str | Path = DEFAULT_JOB_FILE) -> None:
    path = Path(job_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = utc_now()
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _tail(text: str) -> str:
    return (text or "")[-TAIL_LIMIT:]


def _find_job(state: dict, job_id: str) -> dict | None:
    for job in state.get("jobs", []):
        if job.get("job_id") == job_id:
            return job
    return None


def get_job(job_id: str, job_file: str | Path = DEFAULT_JOB_FILE) -> dict | None:
    refresh_running_jobs(job_file)
    return _find_job(load_jobs(job_file), job_id)


def list_jobs(limit: int = 20, job_file: str | Path = DEFAULT_JOB_FILE) -> list[dict]:
    refresh_running_jobs(job_file)
    jobs = load_jobs(job_file).get("jobs", [])
    return list(reversed(jobs[-limit:]))


def _replace_args(args: list[str], values: dict[str, str | None]) -> list[str]:
    output = []
    for item in args:
        output.append(str(values.get(item.strip("{}")) or "") if item.startswith("{") and item.endswith("}") else item)
    return output


def _command_for_action(
    action: str,
    folder: str | None = None,
    *,
    backup_dir: str | None = None,
    log_path: str | None = None,
) -> tuple[list[str], str]:
    definition = ACTION_DEFINITIONS.get(action)
    if not definition:
        raise ValueError(f"Unsupported operator action: {action}")
    if definition.get("requires_folder") and not folder:
        raise ValueError("A folder path is required for this action.")
    if definition.get("requires_backup_dir") and not backup_dir:
        raise ValueError("A backup directory is required for this action.")
    if definition.get("requires_log_path") and not log_path:
        raise ValueError("A replace log path is required for this action.")
    values = {"folder": folder, "backup_dir": backup_dir, "log_path": log_path}
    args = [sys.executable, *_replace_args(definition["args"], values)]
    display = (
        definition["display"]
        .replace("SELECTED_FOLDER", folder or "")
        .replace("BACKUP_DIR", backup_dir or "")
        .replace("LOG_PATH", log_path or "")
    )
    return args, display


def _running_watch_job(state: dict) -> dict | None:
    for job in reversed(state.get("jobs", [])):
        if job.get("job_type") == "start_watch_mode" and job.get("status") == "running":
            return job
    return None


def _summarize(stdout: str, stderr: str, exit_code: int) -> dict:
    summary = {"exit_code": exit_code}
    for text in [stdout, stderr]:
        for line in reversed((text or "").splitlines()):
            stripped = line.strip()
            if stripped:
                summary["last_line"] = stripped
                return summary
    summary["last_line"] = "completed" if exit_code == 0 else "failed"
    return summary


def is_pid_running(pid: int | str | None) -> bool:
    """Return True when pid appears to reference a live process. Never raises."""
    if not pid:
        return False
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            windll = getattr(ctypes, "windll", None)
            if windll is None:
                return False
            process_query_limited_information = 0x1000
            still_active = 259
            handle = windll.kernel32.OpenProcess(
                process_query_limited_information, False, pid_int
            )
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            ok = windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            windll.kernel32.CloseHandle(handle)
            return bool(ok) and exit_code.value == still_active
        except Exception:
            return False
    if not hasattr(os, "kill"):
        return False
    try:
        os.kill(pid_int, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _is_pid_running(pid: int | str | None) -> bool:
    return is_pid_running(pid)


def _monitor_job(job_id: str, process: subprocess.Popen, job_file: str | Path) -> None:
    stdout, stderr = process.communicate()
    with _LOCK:
        state = load_jobs(job_file)
        job = _find_job(state, job_id)
        if not job:
            return
        if job.get("status") == "cancelled":
            job["exit_code"] = process.returncode
        else:
            job["status"] = "completed" if process.returncode == 0 else "failed"
            job["exit_code"] = process.returncode
        job["finished_at"] = utc_now()
        job["stdout_tail"] = _tail(stdout)
        job["stderr_tail"] = _tail(stderr)
        job["result_summary"] = _summarize(stdout, stderr, process.returncode)
        save_jobs(state, job_file)
        _PROCESSES.pop(job_id, None)


def refresh_running_jobs(job_file: str | Path = DEFAULT_JOB_FILE) -> None:
    with _LOCK:
        state = load_jobs(job_file)
        changed = False
        for job in state.get("jobs", []):
            if job.get("status") != "running":
                continue
            process = _PROCESSES.get(job.get("job_id"))
            if process is None:
                try:
                    pid_live = _is_pid_running(job.get("pid"))
                except Exception:
                    continue
                if pid_live:
                    continue
                job["status"] = "failed"
                job["finished_at"] = utc_now()
                job["stderr_tail"] = _tail(
                    (job.get("stderr_tail") or "")
                    + "\nJob process ended before the operator server captured output."
                )
                job["result_summary"] = {
                    "last_line": "stale running job reconciled",
                    "exit_code": job.get("exit_code"),
                }
                changed = True
                continue
            code = process.poll()
            if code is not None:
                job["status"] = "completed" if code == 0 else "failed"
                job["exit_code"] = code
                job["finished_at"] = utc_now()
                changed = True
        if changed:
            save_jobs(state, job_file)


def start_job(
    action: str,
    *,
    folder: str | None = None,
    backup_dir: str | None = None,
    log_path: str | None = None,
    job_file: str | Path = DEFAULT_JOB_FILE,
) -> dict:
    definition = ACTION_DEFINITIONS.get(action)
    if not definition:
        raise ValueError(f"Unsupported operator action: {action}")
    args, display = _command_for_action(action, folder, backup_dir=backup_dir, log_path=log_path)
    with _LOCK:
        state = load_jobs(job_file)
        if definition.get("singleton") and _running_watch_job(state):
            raise RuntimeError("Watch mode is already running.")
        job = {
            "job_id": uuid.uuid4().hex,
            "job_type": action,
            "status": "queued",
            "created_at": utc_now(),
            "started_at": "",
            "finished_at": "",
            "command": display,
            "args": args,
            "stdout_tail": "",
            "stderr_tail": "",
            "exit_code": None,
            "result_summary": {},
            "pid": None,
            "cancellable": bool(definition.get("cancellable")),
        }
        state["jobs"].append(job)
        save_jobs(state, job_file)

    process = subprocess.Popen(
        args,
        cwd=project_path("."),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    with _LOCK:
        state = load_jobs(job_file)
        stored = _find_job(state, job["job_id"])
        if stored:
            stored["status"] = "running"
            stored["started_at"] = utc_now()
            stored["pid"] = process.pid
            save_jobs(state, job_file)
        _PROCESSES[job["job_id"]] = process

    thread = threading.Thread(target=_monitor_job, args=(job["job_id"], process, job_file), daemon=True)
    thread.start()
    return get_job(job["job_id"], job_file) or job


def stop_job(job_id: str, job_file: str | Path = DEFAULT_JOB_FILE) -> dict:
    with _LOCK:
        state = load_jobs(job_file)
        job = _find_job(state, job_id)
        if not job:
            return {"ok": False, "error": "Job not found."}
        if job.get("status") != "running":
            return {"ok": True, "message": "Job is already stopped.", "job": job}
        if not job.get("cancellable"):
            return {"ok": False, "error": "Job is not cancellable.", "job": job}
        process = _PROCESSES.get(job_id)
    if process is not None:
        try:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        except ProcessLookupError:
            pass
    else:
        return {
            "ok": False,
            "error": "Running process handle is not available in this server session; refusing to stop by PID alone.",
            "job": job,
        }
    with _LOCK:
        state = load_jobs(job_file)
        job = _find_job(state, job_id)
        if job:
            job["status"] = "cancelled"
            job["finished_at"] = utc_now()
            job["result_summary"] = {"last_line": "cancelled by operator"}
            save_jobs(state, job_file)
        _PROCESSES.pop(job_id, None)
    return {"ok": True, "message": "Job stopped.", "job": get_job(job_id, job_file)}


def stop_running_watch(job_file: str | Path = DEFAULT_JOB_FILE) -> dict:
    state = load_jobs(job_file)
    job = _running_watch_job(state)
    if not job:
        return {"ok": True, "message": "No running watch job."}
    return stop_job(job["job_id"], job_file)


def operator_state(job_file: str | Path = DEFAULT_JOB_FILE) -> dict:
    jobs = list_jobs(limit=20, job_file=job_file)
    current = next((job for job in jobs if job.get("status") == "running"), None)
    last = jobs[0] if jobs else None
    watch = next((job for job in jobs if job.get("job_type") == "start_watch_mode" and job.get("status") == "running"), None)
    return {
        "current_job": current,
        "last_job": last,
        "watch_mode": {"running": bool(watch), "job": watch},
        "jobs": jobs,
    }
