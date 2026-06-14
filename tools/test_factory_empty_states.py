import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

import app as app_module
from config import project_path


def run_cmd(args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def make_temp_root():
    root = project_path("data/temp") / f"empty_state_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_empty_watch_folder_and_original_unchanged():
    root = make_temp_root()
    try:
        watch = root / "watch"
        watch.mkdir()
        empty = run_cmd([sys.executable, "tools/watch_videoautopipeline_outputs.py", str(watch), "--once", "--dry-run", "--stable-seconds", "0"])
        output = empty.stdout + empty.stderr
        assert empty.returncode == 0
        assert "No MP4 files found yet" in output
        assert "Traceback" not in output

        clip = watch / "original.mp4"
        clip.write_bytes(b"original bytes")
        before = clip.stat()
        dry = run_cmd(
            [
                sys.executable,
                "tools/watch_videoautopipeline_outputs.py",
                str(watch),
                "--once",
                "--dry-run",
                "--stable-seconds",
                "0",
                "--state-file",
                str(root / "watch_state.json"),
            ]
        )
        assert dry.returncode == 0, dry.stderr
        after = clip.stat()
        assert before.st_size == after.st_size
        assert before.st_mtime_ns == after.st_mtime_ns
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_missing_and_empty_folder_clis_are_friendly():
    root = make_temp_root()
    try:
        missing = root / "missing"
        batch = run_cmd([sys.executable, "tools/batch_qc_folder.py", str(missing), "--dry-run"])
        assert batch.returncode == 1
        assert "Suggested next command" in batch.stdout + batch.stderr
        assert "Traceback" not in batch.stdout + batch.stderr

        auto = run_cmd([sys.executable, "tools/auto_qc_fix_folder.py", str(missing), "--dry-run"])
        assert auto.returncode == 1
        assert "Suggested next command" in auto.stdout + auto.stderr
        assert "Traceback" not in auto.stdout + auto.stderr

        empty = root / "empty"
        empty.mkdir()
        batch_empty = run_cmd([sys.executable, "tools/batch_qc_folder.py", str(empty), "--dry-run"])
        assert batch_empty.returncode == 0
        assert "No MP4/MOV/MKV/WebM files found" in batch_empty.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_control_center_empty_state_copy():
    original = {
        "orchestrator_status": app_module.orchestrator_status,
        "queue_stats": app_module.queue_stats,
        "report_payload": app_module.report_payload,
        "history_summary": app_module.history_summary,
        "recent_logs": app_module.recent_logs,
        "load_state": app_module.load_state,
        "detect_videoautopipeline_outputs": app_module.detect_videoautopipeline_outputs,
        "recent_auto_qc_runs": app_module.recent_auto_qc_runs,
    }
    try:
        app_module.orchestrator_status = lambda: {
            "orchestrator_state": "booting",
            "health": {
                "state": "healthy",
                "disk": {"free_bytes": 1000},
                "pipeline": {"state": "healthy"},
                "cpu": {"state": "healthy"},
                "ram": {"state": "healthy"},
                "watch": {},
            },
        }
        app_module.queue_stats = lambda: {"total": 0, "counts": {}, "items": []}
        app_module.report_payload = lambda view="all-time": {"counts": {"accept_rate": 0}}
        app_module.history_summary = lambda: {"recent": []}
        app_module.recent_logs = lambda limit=20: []
        app_module.load_state = lambda path: {"files": {}}
        app_module.detect_videoautopipeline_outputs = lambda: {"found": False, "candidates": [], "recommended_input_folder": ""}
        app_module.recent_auto_qc_runs = lambda: []

        client = TestClient(app_module.app)
        response = client.get("/control-center")
        assert response.status_code == 200
        text = response.text
        assert "No queue yet" in text
        assert "No history yet" in text
        assert "No logs yet" in text
        assert "No watch state yet" in text
        assert "No VideoAutoPipeline MP4 output folder detected yet" in text
        assert "No latest run yet" in text
        assert "py tools\\run_orchestrator.py --once --dry-run" in text
    finally:
        for name, value in original.items():
            setattr(app_module, name, value)


def main() -> int:
    test_empty_watch_folder_and_original_unchanged()
    test_missing_and_empty_folder_clis_are_friendly()
    test_control_center_empty_state_copy()
    print("test_factory_empty_states: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
