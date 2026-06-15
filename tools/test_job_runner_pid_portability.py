import os
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.job_runner import is_pid_running, refresh_running_jobs, save_jobs


def test_non_windows_pid_check_does_not_crash():
    with mock.patch.object(os, "name", "posix"):
        with mock.patch.object(os, "kill", side_effect=ProcessLookupError):
            assert is_pid_running(12345) is False
        with mock.patch.object(os, "kill", side_effect=PermissionError):
            assert is_pid_running(12345) is True
        with mock.patch.object(os, "kill", side_effect=OSError("unsupported")):
            assert is_pid_running(12345) is False
        with mock.patch.object(os, "kill", return_value=None):
            assert is_pid_running(12345) is True


def test_missing_os_kill_returns_false_safely():
    with mock.patch.object(os, "name", "posix"):
        with mock.patch("modules.job_runner.hasattr", return_value=False):
            assert is_pid_running(99) is False


def test_windows_pid_check_handles_missing_windll():
    with mock.patch.object(os, "name", "nt"):
        import ctypes

        with mock.patch.object(ctypes, "windll", None, create=True):
            assert is_pid_running(12345) is False


def test_refresh_running_jobs_survives_pid_check_failure():
    root = ROOT / "data" / "temp" / "pid_portability_test"
    job_file = root / "jobs.json"
    root.mkdir(parents=True, exist_ok=True)
    try:
        save_jobs(
            {
                "version": 1,
                "jobs": [
                    {
                        "job_id": "stale",
                        "job_type": "dry_run_orchestrator",
                        "status": "running",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "started_at": "2026-01-01T00:00:00+00:00",
                        "finished_at": "",
                        "command": "py tools\\run_orchestrator.py --once --dry-run --json",
                        "args": [sys.executable, "tools/run_orchestrator.py"],
                        "stdout_tail": "",
                        "stderr_tail": "",
                        "exit_code": None,
                        "result_summary": {},
                        "pid": 42424242,
                        "cancellable": False,
                    }
                ],
            },
            job_file,
        )
        with mock.patch("modules.job_runner.is_pid_running", side_effect=RuntimeError("boom")):
            refresh_running_jobs(job_file)
    finally:
        import shutil

        shutil.rmtree(root, ignore_errors=True)


def test_invalid_pid_inputs_are_safe():
    assert is_pid_running(None) is False
    assert is_pid_running("") is False
    assert is_pid_running("not-a-pid") is False
    assert is_pid_running(-1) is False
    assert is_pid_running(0) is False


def main() -> int:
    test_non_windows_pid_check_does_not_crash()
    test_missing_os_kill_returns_false_safely()
    test_windows_pid_check_handles_missing_windll()
    test_refresh_running_jobs_survives_pid_check_failure()
    test_invalid_pid_inputs_are_safe()
    print("test_job_runner_pid_portability: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
