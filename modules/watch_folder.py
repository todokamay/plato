from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from config import project_path
from modules.videoautopipeline_detector import DEFAULT_VIDEOAUTOPIPELINE_ROOT, detect_videoautopipeline_outputs


DEFAULT_STATE_FILE = project_path("data/watch_state/watch_state.json")
DEFAULT_LOG_FILE = project_path("data/watch_state/watch_runs.jsonl")
WATCH_STATUSES = {"seen", "stable", "processing", "processed", "failed", "skipped"}


@dataclass
class WatchOptions:
    watch_folder: str | Path
    state_file: str | Path = DEFAULT_STATE_FILE
    output_dir: str | Path | None = None
    auto_fix: bool = False
    copy_results: bool = False
    dry_run: bool = False
    once: bool = False
    poll_interval: float = 10.0
    stable_seconds: float = 5.0
    max_files_per_cycle: int = 10
    allow_original_short: bool = False
    short_clip_min_duration: float = 5.0


WatchExecutor = Callable[[Path, WatchOptions, str, int], dict]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now(now_func: Callable[[], datetime] = utc_now) -> str:
    return now_func().isoformat(timespec="seconds")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _state_template() -> dict:
    return {"version": 1, "updated_at": iso_now(), "files": {}}


def load_state(path: str | Path) -> dict:
    state_path = Path(path)
    if not state_path.exists():
        return _state_template()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _state_template()
    if not isinstance(data, dict):
        return _state_template()
    data.setdefault("version", 1)
    data.setdefault("files", {})
    return data


def save_state(path: str | Path, state: dict) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = iso_now()
    temp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(state_path)


def append_watch_log(state_file: str | Path, payload: dict) -> None:
    log_path = Path(state_file).with_name("watch_runs.jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def fallback_command() -> str:
    return r"py tools\watch_videoautopipeline_outputs.py PATH --once --dry-run"


def resolve_watch_folder(
    input_folder: str | Path | None,
    *,
    detect_videoautopipeline_outputs_enabled: bool = False,
    videoautopipeline_root: str | Path = DEFAULT_VIDEOAUTOPIPELINE_ROOT,
) -> tuple[Path, dict | None]:
    if input_folder:
        folder = Path(input_folder)
        if not folder.exists() or not folder.is_dir():
            raise FileNotFoundError(f"Watch folder not found: {folder}")
        return folder, None

    if detect_videoautopipeline_outputs_enabled:
        detection = detect_videoautopipeline_outputs(videoautopipeline_root)
        recommended = detection.get("recommended_input_folder")
        if recommended:
            folder = Path(recommended)
            if folder.exists() and folder.is_dir():
                return folder, detection
        raise FileNotFoundError(
            "No VideoAutoPipeline MP4 output folders found. "
            f"Fallback command: {fallback_command()}"
        )

    raise FileNotFoundError("Watch folder is required unless --detect-videoautopipeline-outputs is used.")


def _mp4_files(folder: Path) -> list[Path]:
    try:
        return sorted(
            [path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".mp4"],
            key=lambda path: str(path).lower(),
        )
    except OSError:
        return []


def _stat(path: Path) -> dict:
    stat = path.stat()
    return {"file_size": stat.st_size, "mtime": stat.st_mtime, "mtime_ns": stat.st_mtime_ns}


def _entry_for(path: Path, stat: dict, now_text: str) -> dict:
    return {
        "file_path": str(path.resolve()),
        "file_size": stat["file_size"],
        "mtime": stat["mtime"],
        "first_seen_time": now_text,
        "processed_time": "",
        "last_result": {},
        "run_id": "",
        "status": "seen",
    }


def _same_signature(entry: dict, stat: dict) -> bool:
    return entry.get("file_size") == stat["file_size"] and entry.get("mtime") == stat["mtime"]


def _age_seconds(entry: dict, now: datetime) -> float:
    first_seen = _parse_time(entry.get("first_seen_time"))
    if not first_seen:
        return 0.0
    return max(0.0, (now - first_seen).total_seconds())


def _update_seen_files(folder: Path, state: dict, stable_seconds: float, now: datetime) -> tuple[list[Path], int]:
    files = _mp4_files(folder)
    now_text = now.isoformat(timespec="seconds")
    new_count = 0
    for path in files:
        resolved = str(path.resolve())
        stat = _stat(path)
        entry = state["files"].get(resolved)
        if not entry:
            state["files"][resolved] = _entry_for(path, stat, now_text)
            new_count += 1
            entry = state["files"][resolved]
            if stable_seconds <= 0:
                entry["status"] = "stable"
        elif not _same_signature(entry, stat):
            entry.update(_entry_for(path, stat, now_text))
            new_count += 1
        elif entry.get("status") in {"seen", "stable", "skipped"} and _age_seconds(entry, now) >= stable_seconds:
            entry["status"] = "stable"
    return files, new_count


def _ready_files(files: list[Path], state: dict, max_files: int) -> list[Path]:
    ready = []
    for path in files:
        entry = state["files"].get(str(path.resolve())) or {}
        if entry.get("status") == "stable":
            ready.append(path)
    return ready[: max(0, int(max_files))]


def _cycle_id(now: datetime) -> str:
    return "watch_" + now.strftime("%Y%m%d_%H%M%S_%f")


def _stage_files(files: list[Path], state_file: Path, cycle_id: str) -> Path:
    staging = state_file.parent / "cycles" / cycle_id / "input"
    staging.mkdir(parents=True, exist_ok=True)
    for source in files:
        shutil.copy2(source, staging / source.name)
    return staging


def _mark_skipped(files: list[Path], state: dict, now_text: str, reason: str) -> list[dict]:
    results = []
    for path in files:
        entry = state["files"][str(path.resolve())]
        entry["status"] = "skipped"
        entry["processed_time"] = now_text
        entry["run_id"] = ""
        entry["last_result"] = {"dry_run": True, "reason": reason}
        results.append({"file_path": str(path.resolve()), "status": "skipped", "reason": reason})
    return results


def _mark_processing(files: list[Path], state: dict, now_text: str) -> dict[str, dict]:
    before = {}
    for path in files:
        resolved = str(path.resolve())
        before[resolved] = _stat(path)
        entry = state["files"][resolved]
        entry["status"] = "processing"
        entry["last_result"] = {"started_at": now_text}
    return before


def _result_by_filename(payload: dict) -> dict[str, dict]:
    return {row.get("filename"): row for row in payload.get("clips", []) if row.get("filename")}


def _mark_processed(files: list[Path], state: dict, payload: dict, before: dict[str, dict], now_text: str) -> list[dict]:
    rows = _result_by_filename(payload)
    results = []
    run_id = payload.get("run_id") or ""
    for path in files:
        resolved = str(path.resolve())
        entry = state["files"][resolved]
        row = rows.get(path.name, {})
        unchanged = True
        try:
            unchanged = _same_signature(entry, _stat(path)) and before[resolved]["mtime_ns"] == path.stat().st_mtime_ns
        except OSError:
            unchanged = False
        if unchanged:
            entry["status"] = "processed"
            entry["processed_time"] = now_text
            entry["run_id"] = run_id
            entry["last_result"] = {
                "run_id": run_id,
                "final_bucket": row.get("final_bucket", ""),
                "failure_reason": row.get("failure_reason", ""),
                "fixed_path": row.get("fixed_path", ""),
                "final_output_path": row.get("final_output_path", ""),
            }
        else:
            entry["status"] = "failed"
            entry["processed_time"] = now_text
            entry["run_id"] = run_id
            entry["last_result"] = {"run_id": run_id, "error": "original file changed during processing"}
        results.append({"file_path": resolved, "status": entry["status"], "last_result": entry["last_result"]})
    return results


def _mark_failed(files: list[Path], state: dict, now_text: str, error: str) -> list[dict]:
    results = []
    for path in files:
        resolved = str(path.resolve())
        entry = state["files"][resolved]
        entry["status"] = "failed"
        entry["processed_time"] = now_text
        entry["last_result"] = {"error": error}
        results.append({"file_path": resolved, "status": "failed", "error": error})
    return results


def _default_executor() -> WatchExecutor:
    # ponytail: compatibility shim; new runtime entrypoints live in watch_engine.
    from modules.watch_engine import run_auto_qc_executor

    return run_auto_qc_executor


def run_watch_cycle(
    options: WatchOptions,
    *,
    now_func: Callable[[], datetime] = utc_now,
    executor: WatchExecutor | None = None,
) -> dict:
    folder = Path(options.watch_folder)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Watch folder not found: {folder}")

    state_path = Path(options.state_file)
    state = load_state(state_path)
    now = now_func()
    now_text = now.isoformat(timespec="seconds")
    cycle_id = _cycle_id(now)
    files, new_count = _update_seen_files(folder, state, options.stable_seconds, now)
    ready = _ready_files(files, state, options.max_files_per_cycle)
    results: list[dict] = []
    auto_qc_payload: dict | None = None

    if ready and options.dry_run:
        results = _mark_skipped(ready, state, now_text, "dry run: auto-QC not called")
    elif ready:
        before = _mark_processing(ready, state, now_text)
        save_state(state_path, state)
        staging_dir = _stage_files(ready, state_path, cycle_id)
        try:
            auto_qc_payload = (executor or _default_executor())(staging_dir, options, cycle_id, len(ready))
            results = _mark_processed(ready, state, auto_qc_payload, before, now_text)
        except Exception as exc:
            results = _mark_failed(ready, state, now_text, str(exc))
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir.parent, ignore_errors=True)

    processed_count = sum(1 for item in results if item.get("status") == "processed")
    skipped_count = sum(1 for item in results if item.get("status") == "skipped")
    failed_count = sum(1 for item in results if item.get("status") == "failed")
    payload = {
        "cycle_id": cycle_id,
        "created_at": now_text,
        "watch_folder": str(folder.resolve()),
        "state_file": str(state_path),
        "detected_count": len(files),
        "new_count": new_count,
        "stable_count": len(ready),
        "processing_count": len(ready) if ready and not options.dry_run else 0,
        "processed_count": processed_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "auto_qc_run_id": (auto_qc_payload or {}).get("run_id", ""),
        "results": results,
    }
    save_state(state_path, state)
    append_watch_log(state_path, payload)
    return payload


def run_watch(
    options: WatchOptions,
    *,
    now_func: Callable[[], datetime] = utc_now,
    sleep_func: Callable[[float], None] = time.sleep,
    executor: WatchExecutor | None = None,
) -> list[dict]:
    cycles = []
    while True:
        payload = run_watch_cycle(options, now_func=now_func, executor=executor)
        cycles.append(payload)
        if options.once:
            return cycles
        sleep_func(options.poll_interval)
