import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules import watch_engine
from modules.watch_folder import WatchOptions, load_state


def make_root():
    root = project_path("data/temp") / f"watch_responsibility_{uuid.uuid4().hex[:8]}"
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


def payload_for(filenames):
    return {
        "run_id": "fake_watch_engine_run",
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


def test_dry_run_stays_detection_only():
    root = make_root()
    try:
        source = write(root / "watch" / "dry.mp4")

        def should_not_run(*args):
            raise AssertionError("executor should not run during dry-run")

        result = watch_engine.run_watch_cycle(options(root, dry_run=True), executor=should_not_run)
        state = load_state(root / "state" / "watch_state.json")

        assert result["skipped_count"] == 1
        assert result["processed_count"] == 0
        assert state["files"][str(source.resolve())]["status"] == "skipped"
        assert state["files"][str(source.resolve())]["last_result"]["dry_run"] is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_staging_copy_and_original_safety_are_unchanged():
    root = make_root()
    seen = {}
    try:
        source = write(root / "watch" / "clip.mp4", b"original-bytes")
        before = source.stat()

        def executor(staging_dir, opts, cycle_id, ready_count):
            staged = Path(staging_dir)
            filenames = sorted(path.name for path in staged.glob("*.mp4"))
            seen["cycle_id"] = cycle_id
            seen["ready_count"] = ready_count
            seen["staging_dir"] = staged
            seen["filenames"] = filenames
            seen["staged_bytes"] = (staged / "clip.mp4").read_bytes()
            seen["output_dir"] = opts.output_dir
            return payload_for(filenames)

        result = watch_engine.run_watch_cycle(options(root), executor=executor)
        after = source.stat()

        assert result["processed_count"] == 1
        assert seen["filenames"] == ["clip.mp4"]
        assert seen["ready_count"] == 1
        assert seen["staging_dir"].name == "input"
        assert seen["staging_dir"].parent.name == seen["cycle_id"]
        assert seen["staging_dir"].parent.parent == root / "state" / "cycles"
        assert seen["staged_bytes"] == b"original-bytes"
        assert not seen["staging_dir"].parent.exists()
        assert before.st_size == after.st_size
        assert before.st_mtime_ns == after.st_mtime_ns
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_auto_qc_executor_preserves_runtime_flags():
    root = make_root()
    original = watch_engine.run_auto_qc_fix
    captured = {}
    try:
        staging = root / "stage"
        staging.mkdir(parents=True, exist_ok=True)
        opts = options(
            root,
            auto_fix=True,
            copy_results=True,
            allow_original_short=True,
            short_clip_min_duration=4.5,
        )

        def fake_auto_qc(input_folder, **kwargs):
            captured["input_folder"] = Path(input_folder)
            captured.update(kwargs)
            return {"run_id": "fake_auto_qc", "clips": []}

        watch_engine.run_auto_qc_fix = fake_auto_qc
        result = watch_engine.run_auto_qc_executor(staging, opts, "cycle_1", 2)

        assert result["run_id"] == "fake_auto_qc"
        assert captured["input_folder"] == staging
        assert captured["auto_fix"] is True
        assert captured["copy_results"] is True
        assert captured["output_dir"] == root / "out" / "cycle_1"
        assert captured["limit"] == 2
        assert captured["allow_original_short"] is True
        assert captured["short_clip_min_duration"] == 4.5
        assert captured["force"] is True
    finally:
        watch_engine.run_auto_qc_fix = original
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    test_dry_run_stays_detection_only()
    test_staging_copy_and_original_safety_are_unchanged()
    test_auto_qc_executor_preserves_runtime_flags()
    print("test_watch_responsibility: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
