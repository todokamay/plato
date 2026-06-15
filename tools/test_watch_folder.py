import shutil
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules.watch_folder import WatchOptions, load_state, resolve_watch_folder, run_watch, run_watch_cycle


def fake_executor(calls):
    def _run(staging_dir, options, cycle_id, ready_count):
        folder = Path(staging_dir)
        filenames = sorted(path.name for path in folder.glob("*.mp4"))
        calls.append(
            {
                "input_folder": folder,
                "filenames": filenames,
                "options": options,
                "cycle_id": cycle_id,
                "ready_count": ready_count,
            }
        )
        return {
            "run_id": f"fake_run_{len(calls)}",
            "counts": {"scanned_count": len(filenames)},
            "paths": {},
            "clips": [
                {
                    "filename": filename,
                    "final_bucket": "safe_to_test",
                    "failure_reason": "",
                    "fixed_path": "",
                    "final_output_path": "",
                }
                for filename in filenames
            ],
        }

    return _run


def make_root():
    root = project_path("data/temp") / f"watch_test_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def options(root, **overrides):
    data = {
        "watch_folder": root / "watch",
        "state_file": root / "state" / "watch_state.json",
        "output_dir": root / "out",
        "once": True,
        "stable_seconds": 0,
        "max_files_per_cycle": 10,
    }
    data.update(overrides)
    return WatchOptions(**data)


def write(path: Path, data: bytes = b"video") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_detects_mp4_and_ignores_non_mp4():
    root = make_root()
    calls = []
    try:
        watch = root / "watch"
        source = write(watch / "new_clip.mp4")
        write(watch / "notes.txt", b"not video")
        before = source.stat()

        payload = run_watch_cycle(options(root), executor=fake_executor(calls))
        state = load_state(root / "state" / "watch_state.json")
        files = state["files"]

        assert payload["detected_count"] == 1
        assert payload["processed_count"] == 1
        assert calls[0]["filenames"] == ["new_clip.mp4"]
        assert str(source.resolve()) in files
        assert files[str(source.resolve())]["status"] == "processed"
        assert not any("notes.txt" in key for key in files)
        after = source.stat()
        assert before.st_size == after.st_size
        assert before.st_mtime_ns == after.st_mtime_ns
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_waits_for_stable_file_and_skips_processed_duplicate():
    root = make_root()
    calls = []
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    try:
        source = write(root / "watch" / "wait.mp4")
        opts = options(root, stable_seconds=5)
        executor = fake_executor(calls)

        first = run_watch_cycle(opts, now_func=lambda: base, executor=executor)
        assert first["stable_count"] == 0
        assert len(calls) == 0

        second = run_watch_cycle(opts, now_func=lambda: base + timedelta(seconds=6), executor=executor)
        assert second["stable_count"] == 1
        assert second["processed_count"] == 1
        assert len(calls) == 1

        third = run_watch_cycle(opts, now_func=lambda: base + timedelta(seconds=12), executor=executor)
        assert third["stable_count"] == 0
        assert third["processed_count"] == 0
        assert len(calls) == 1

        state = load_state(root / "state" / "watch_state.json")
        assert state["files"][str(source.resolve())]["status"] == "processed"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_dry_run_does_not_call_auto_qc():
    root = make_root()
    try:
        source = write(root / "watch" / "dry.mp4")

        def should_not_run(*args):
            raise AssertionError("auto-QC should not run during dry-run")

        payload = run_watch_cycle(options(root, dry_run=True), executor=should_not_run)
        state = load_state(root / "state" / "watch_state.json")

        assert payload["skipped_count"] == 1
        assert payload["processed_count"] == 0
        assert state["files"][str(source.resolve())]["status"] == "skipped"
        assert state["files"][str(source.resolve())]["last_result"]["dry_run"] is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_once_mode_exits_after_one_cycle():
    root = make_root()
    calls = []
    try:
        write(root / "watch" / "once.mp4")
        cycles = run_watch(
            options(root, once=True),
            sleep_func=lambda seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
            executor=fake_executor(calls),
        )

        assert len(cycles) == 1
        assert cycles[0]["processed_count"] == 1
        assert len(calls) == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_missing_folder_gives_clear_error():
    root = make_root()
    try:
        try:
            run_watch_cycle(options(root, watch_folder=root / "missing"))
            raise AssertionError("missing folder should fail")
        except FileNotFoundError as exc:
            assert "Watch folder not found" in str(exc)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_detector_fallback_works():
    root = make_root()
    try:
        vap_root = root / "VideoAutoPipeline"
        vap_root.mkdir(parents=True, exist_ok=True)
        try:
            resolve_watch_folder(None, detect_videoautopipeline_outputs_enabled=True, videoautopipeline_root=vap_root)
            raise AssertionError("empty detector root should fail")
        except FileNotFoundError as exc:
            message = str(exc)
            assert "No VideoAutoPipeline MP4 output folders found" in message
            assert "Fallback command" in message
            assert "watch_videoautopipeline_outputs.py" in message
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    test_detects_mp4_and_ignores_non_mp4()
    test_waits_for_stable_file_and_skips_processed_duplicate()
    test_dry_run_does_not_call_auto_qc()
    test_once_mode_exits_after_one_cycle()
    test_missing_folder_gives_clear_error()
    test_detector_fallback_works()
    print("test_watch_folder: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
