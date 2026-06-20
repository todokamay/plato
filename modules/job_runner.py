from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import VIDEOAUTOPIPELINE_OUTPUT_ROOT, VIDEOAUTOPIPELINE_ROOT, project_path


JOB_STATUSES = {"queued", "running", "completed", "failed", "cancelled"}
DEFAULT_JOB_FILE = project_path("data/jobs/jobs.json")
TAIL_LIMIT = 8000
FACTORY_PRESETS = {"quality", "balanced", "fast", "archive"}
WHISPER_MODELS = {"small", "medium", "large-v3"}
ALLOW_SAFE_PRESETS = {"balanced", "fast"}

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
    "vap_delivery_scan": {
        "display": r"py tools\process_videoautopipeline_outputs.py SELECTED_FOLDER --dry-run",
        "args": ["tools/process_videoautopipeline_outputs.py", "{folder}", "--dry-run"],
        "requires_folder": True,
        "cancellable": False,
    },
    "vap_delivery_process": {
        "display": r"py tools\process_videoautopipeline_outputs.py SELECTED_FOLDER --auto-fix --copy-results",
        "args": ["tools/process_videoautopipeline_outputs.py", "{folder}", "--auto-fix", "--copy-results"],
        "requires_folder": True,
        "cancellable": False,
    },
    "vap_delivery_send": {
        "display": r"py tools\process_videoautopipeline_outputs.py SELECTED_FOLDER --auto-fix --copy-results --send-telegram",
        "args": ["tools/process_videoautopipeline_outputs.py", "{folder}", "--auto-fix", "--copy-results", "--send-telegram"],
        "requires_folder": True,
        "cancellable": False,
    },
    "open_videoautopipeline_gui": {
        "display": "py VIDEOAUTOPIPELINE_APP",
        "args": [],
        "cancellable": True,
    },
    "vap_generate_longvideos": {
        "display": "py VIDEOAUTOPIPELINE_APP --batch LONGVIDEOS",
        "args": [],
        "requires_input_folder": True,
        "cancellable": False,
    },
    "vap_generate_one_video": {
        "display": "py VIDEOAUTOPIPELINE_APP --worker INPUT.mp4",
        "args": [],
        "requires_input_file": True,
        "cancellable": False,
    },
    "vap_batch_generate_folder": {
        "display": "py VIDEOAUTOPIPELINE_APP --batch INPUT_FOLDER",
        "args": [],
        "requires_input_folder": True,
        "cancellable": False,
    },
    "vap_batch_dry_run": {
        "display": "py VIDEOAUTOPIPELINE_APP --batch INPUT_FOLDER --dry-run",
        "args": [],
        "requires_input_folder": True,
        "cancellable": False,
    },
    "vap_resume_failed": {
        "display": "py VIDEOAUTOPIPELINE_APP INPUT --resume",
        "args": [],
        "cancellable": False,
    },
    "vap_status": {
        "display": "py VIDEOAUTOPIPELINE_APP --worker INPUT.mp4 --status-only",
        "args": [],
        "cancellable": False,
    },
    "run_videoautopipeline_worker": {
        "display": "py VIDEOAUTOPIPELINE_APP --worker INPUT.mp4",
        "args": [],
        "requires_input_file": True,
        "cancellable": False,
    },
    "run_videoautopipeline_batch": {
        "display": "py VIDEOAUTOPIPELINE_APP --batch INPUT_FOLDER",
        "args": [],
        "requires_input_folder": True,
        "cancellable": False,
    },
    "process_videoautopipeline_outputs": {
        "display": r"py tools\process_videoautopipeline_outputs.py OUTPUT_ROOT --auto-fix --copy-results --dry-run",
        "args": [],
        "requires_output_root": True,
        "cancellable": False,
    },
    "vap_dry_run_rerender_request": {
        "display": r"py VIDEOAUTOPIPELINE_ROOT\tools\process_rerender_request.py REQUEST.json --dry-run --json",
        "args": [],
        "cancellable": False,
    },
    "import_rerender_result": {
        "display": r"py tools\import_rerender_result.py STATUS.json",
        "args": [],
        "cancellable": False,
    },
    "process_completed_rerenders": {
        "display": r"py tools\process_videoautopipeline_outputs.py OUTPUT_ROOT --include-rerenders --auto-fix --copy-results --dry-run",
        "args": [],
        "requires_output_root": True,
        "cancellable": False,
    },
    "repair_latest_rerender_request": {
        "display": r"py tools\run_rerender_repair_loop.py --vap-root VIDEOAUTOPIPELINE_ROOT --output-root OUTPUT_ROOT --json",
        "args": [],
        "requires_output_root": True,
        "cancellable": False,
    },
    "run_full_videoautopipeline_to_plato_flow": {
        "display": r"py tools\run_videoautopipeline_full_flow.py --vap-root VIDEOAUTOPIPELINE_ROOT --output-root OUTPUT_ROOT",
        "args": [],
        "requires_output_root": True,
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
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        for attempt in range(5):
            try:
                temp_path.replace(path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


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


def _vap_paths(
    vap_root: str | Path | None = None,
    output_root: str | Path | None = None,
) -> tuple[Path, Path, Path]:
    root = Path(vap_root or VIDEOAUTOPIPELINE_ROOT)
    output = Path(output_root or VIDEOAUTOPIPELINE_OUTPUT_ROOT)
    return root, root / "app.py", output


def _add_process_flags(
    args: list[str],
    *,
    dry_run: bool = True,
    auto_fix: bool = True,
    copy_results: bool = True,
    send_telegram: bool = False,
) -> None:
    if auto_fix:
        args.append("--auto-fix")
    if copy_results:
        args.append("--copy-results")
    if dry_run:
        args.append("--dry-run")
    if send_telegram:
        args.append("--send-telegram")


def _positive_int(value, default: int = 0) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return default


def _factory_preset(value: str | None) -> str:
    preset = str(value or "quality").strip().lower()
    return preset if preset in FACTORY_PRESETS else "quality"


def _whisper_model(value: str | None) -> str:
    model = str(value or "medium").strip().lower()
    return model if model in WHISPER_MODELS else "medium"


def _vap_env(
    *,
    vap_root: str | Path | None = None,
    output_root: str | Path | None = None,
    davinci_mode: str = "required",
    cleanup_mode: str = "keep_all",
    factory_preset: str = "quality",
    max_candidates: int | str | None = 12,
    top_render_count: int | str | None = 6,
    stop_after_approved: int | str | None = 3,
    whisper_model: str = "medium",
) -> dict[str, str]:
    root, _, output = _vap_paths(vap_root, output_root)
    mode = davinci_mode if davinci_mode in {"required", "optional", "disabled"} else "required"
    cleanup = cleanup_mode if cleanup_mode in {"keep_final_only", "keep_all", "dry_run"} else "keep_all"
    preset = _factory_preset(factory_preset)
    max_count = _positive_int(max_candidates, 12)
    render_count = _positive_int(top_render_count, 6)
    approved_count = _positive_int(stop_after_approved, 3)
    whisper = _whisper_model(whisper_model)
    return {
        "SEND_MODE": "after_plato",
        "VAP_SEND_MODE": "after_plato",
        "VAP_DAVINCI_MODE": mode,
        "VAP_REQUIRE_DAVINCI": "true" if mode == "required" else "false",
        "FACTORY_PRESET": preset,
        "VAP_MAX_CANDIDATES": str(max_count),
        "VAP_TOP_RENDER_COUNT": str(render_count),
        "VAP_STOP_AFTER_APPROVED": str(approved_count),
        "VAP_WHISPER_MODEL": whisper,
        "VAP_ALLOW_SAFE_TO_TEST": "true" if preset in ALLOW_SAFE_PRESETS else "false",
        "ALLOW_SAFE_TO_TEST": "true" if preset in ALLOW_SAFE_PRESETS else "false",
        "VAP_OUTPUT_DIR": str(output),
        "VIDEOAUTOPIPELINE_ROOT": str(root),
        "VIDEOAUTOPIPELINE_OUTPUT_ROOT": str(output),
        "CLEANUP_MODE": cleanup,
    }


def _command_for_action(
    action: str,
    folder: str | None = None,
    *,
    backup_dir: str | None = None,
    log_path: str | None = None,
    input_file: str | None = None,
    input_folder: str | None = None,
    output_root: str | None = None,
    limit: int | None = None,
    dry_run: bool = True,
    auto_fix: bool = True,
    copy_results: bool = True,
    send_telegram: bool = False,
    vap_root: str | None = None,
    davinci_mode: str = "required",
    cleanup_mode: str = "keep_all",
    factory_preset: str = "quality",
    max_candidates: int | str | None = 12,
    top_render_count: int | str | None = 6,
    stop_after_approved: int | str | None = 3,
    whisper_model: str = "medium",
    confirm_real_rerender: bool = False,
    confirm_cleanup: bool = False,
) -> tuple[list[str], str]:
    definition = ACTION_DEFINITIONS.get(action)
    if not definition:
        raise ValueError(f"Unsupported operator action: {action}")
    root, app_path, output = _vap_paths(vap_root, output_root)
    if action == "open_videoautopipeline_gui":
        return [sys.executable, str(app_path)], f"py {app_path}"
    if action in {"run_videoautopipeline_worker", "vap_generate_one_video"}:
        if not input_file:
            raise ValueError("An input MP4 is required for this action.")
        args = [sys.executable, str(app_path), "--worker", input_file]
        return args, f'py {app_path} --worker "{input_file}"'
    if action in {"run_videoautopipeline_batch", "vap_generate_longvideos", "vap_batch_generate_folder", "vap_batch_dry_run"}:
        if not input_folder:
            raise ValueError("An input folder is required for this action.")
        args = [sys.executable, str(app_path), "--batch", input_folder, "--output-root", str(output)]
        display = f'py {app_path} --batch "{input_folder}" --output-root "{output}"'
        if limit:
            args.extend(["--limit", str(limit)])
            display += f" --limit {limit}"
        if action == "vap_batch_dry_run":
            args.extend(["--dry-run", "--json"])
            display += " --dry-run --json"
        return args, display
    if action == "vap_resume_failed":
        if input_file:
            args = [sys.executable, str(app_path), "--worker", input_file, "--resume"]
            return args, f'py {app_path} --worker "{input_file}" --resume'
        if input_folder:
            args = [sys.executable, str(app_path), "--batch", input_folder, "--output-root", str(output), "--resume"]
            display = f'py {app_path} --batch "{input_folder}" --output-root "{output}" --resume'
            if limit:
                args.extend(["--limit", str(limit)])
                display += f" --limit {limit}"
            return args, display
        raise ValueError("An input MP4 or input folder is required for this action.")
    if action == "vap_status":
        if not input_file:
            raise ValueError("An input MP4 is required for worker status.")
        args = [sys.executable, str(app_path), "--worker", input_file, "--status-only"]
        return args, f'py {app_path} --worker "{input_file}" --status-only'
    if action == "process_videoautopipeline_outputs":
        args = [sys.executable, "tools/process_videoautopipeline_outputs.py", str(output)]
        if _positive_int(stop_after_approved, 3):
            args.extend(["--stop-after-approved", str(_positive_int(stop_after_approved, 3))])
        _add_process_flags(args, dry_run=dry_run, auto_fix=auto_fix, copy_results=copy_results, send_telegram=send_telegram)
        return args, "py " + " ".join(args[1:])
    if action == "vap_dry_run_rerender_request":
        if not input_file:
            raise ValueError("A rerender request JSON path is required.")
        args = [sys.executable, str(root / "tools" / "process_rerender_request.py"), input_file, "--dry-run", "--json", "--output-root", str(output)]
        return args, f'py {root / "tools" / "process_rerender_request.py"} "{input_file}" --dry-run --json --output-root "{output}"'
    if action == "import_rerender_result":
        if not input_file:
            raise ValueError("A rerender status JSON path is required.")
        args = [sys.executable, "tools/import_rerender_result.py", input_file]
        return args, f'py tools/import_rerender_result.py "{input_file}"'
    if action == "process_completed_rerenders":
        args = [sys.executable, "tools/process_videoautopipeline_outputs.py", str(output), "--include-rerenders"]
        if _positive_int(stop_after_approved, 3):
            args.extend(["--stop-after-approved", str(_positive_int(stop_after_approved, 3))])
        _add_process_flags(args, dry_run=dry_run, auto_fix=auto_fix, copy_results=copy_results, send_telegram=False)
        return args, "py " + " ".join(args[1:])
    if action == "repair_latest_rerender_request":
        args = [
            sys.executable,
            "tools/run_rerender_repair_loop.py",
            "--vap-root",
            str(root),
            "--output-root",
            str(output),
            "--json",
        ]
        if confirm_real_rerender:
            args.append("--confirm-real-rerender")
        return args, "py " + " ".join(args[1:])
    if action == "run_full_videoautopipeline_to_plato_flow":
        if not input_file and not input_folder:
            raise ValueError("An input MP4 or input folder is required for this action.")
        args = [
            sys.executable,
            "tools/run_videoautopipeline_full_flow.py",
            "--vap-root",
            str(root),
            "--output-root",
            str(output),
        ]
        if input_file:
            args.extend(["--input-video", input_file])
        if input_folder:
            args.extend(["--input-folder", input_folder])
        if limit:
            args.extend(["--limit", str(limit)])
        args.extend(["--davinci-mode", davinci_mode if davinci_mode in {"required", "optional", "disabled"} else "required"])
        args.extend(["--cleanup-mode", cleanup_mode if cleanup_mode in {"keep_final_only", "keep_all", "dry_run"} else "keep_all"])
        args.extend(["--factory-preset", _factory_preset(factory_preset)])
        args.extend(["--max-candidates", str(_positive_int(max_candidates, 12))])
        args.extend(["--top-render-count", str(_positive_int(top_render_count, 6))])
        args.extend(["--stop-after-approved", str(_positive_int(stop_after_approved, 3))])
        args.extend(["--whisper-model", _whisper_model(whisper_model)])
        if confirm_cleanup:
            args.append("--confirm-cleanup")
        _add_process_flags(args, dry_run=dry_run, auto_fix=auto_fix, copy_results=copy_results, send_telegram=send_telegram)
        return args, "py " + " ".join(args[1:])
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


def _decode_output(chunk: bytes | str) -> str:
    return chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else chunk


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
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    def reader(stream, key: str, parts: list[str]) -> None:
        if stream is None:
            return
        count = 0
        while True:
            chunk = stream.readline()
            if not chunk:
                break
            line = _decode_output(chunk)
            count += 1
            parts.append(line)
            if len(parts) > 200:
                parts[:] = [_tail("".join(parts))]
            if count != 1 and count % 25 != 0:
                continue
            with _LOCK:
                state = load_jobs(job_file)
                job = _find_job(state, job_id)
                if not job:
                    return
                job[key] = _tail("".join(parts))
                save_jobs(state, job_file)

    stdout_thread = threading.Thread(target=reader, args=(process.stdout, "stdout_tail", stdout_parts), daemon=True)
    stderr_thread = threading.Thread(target=reader, args=(process.stderr, "stderr_tail", stderr_parts), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    process.wait()
    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)
    stdout = "".join(stdout_parts)
    stderr = "".join(stderr_parts)
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
    input_file: str | None = None,
    input_folder: str | None = None,
    output_root: str | None = None,
    limit: int | None = None,
    dry_run: bool = True,
    auto_fix: bool = True,
    copy_results: bool = True,
    send_telegram: bool = False,
    vap_root: str | None = None,
    davinci_mode: str = "required",
    cleanup_mode: str = "keep_all",
    factory_preset: str = "quality",
    max_candidates: int | str | None = 12,
    top_render_count: int | str | None = 6,
    stop_after_approved: int | str | None = 3,
    whisper_model: str = "medium",
    confirm_real_rerender: bool = False,
    confirm_cleanup: bool = False,
    job_file: str | Path = DEFAULT_JOB_FILE,
) -> dict:
    definition = ACTION_DEFINITIONS.get(action)
    if not definition:
        raise ValueError(f"Unsupported operator action: {action}")
    args, display = _command_for_action(
        action,
        folder,
        backup_dir=backup_dir,
        log_path=log_path,
        input_file=input_file,
        input_folder=input_folder,
        output_root=output_root,
        limit=limit,
        dry_run=dry_run,
        auto_fix=auto_fix,
        copy_results=copy_results,
        send_telegram=send_telegram,
        vap_root=vap_root,
        davinci_mode=davinci_mode,
        cleanup_mode=cleanup_mode,
        factory_preset=factory_preset,
        max_candidates=max_candidates,
        top_render_count=top_render_count,
        stop_after_approved=stop_after_approved,
        whisper_model=whisper_model,
        confirm_real_rerender=confirm_real_rerender,
        confirm_cleanup=confirm_cleanup,
    )
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    if action.startswith("run_videoautopipeline") or action.startswith("vap_") or action in {"process_videoautopipeline_outputs", "repair_latest_rerender_request"}:
        env.update(_vap_env(
            vap_root=vap_root,
            output_root=output_root,
            davinci_mode=davinci_mode,
            cleanup_mode=cleanup_mode,
            factory_preset=factory_preset,
            max_candidates=max_candidates,
            top_render_count=top_render_count,
            stop_after_approved=stop_after_approved,
            whisper_model=whisper_model,
        ))
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
        shell=False,
        env=env,
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
