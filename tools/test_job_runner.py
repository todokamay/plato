import shutil
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules.job_runner import get_job, list_jobs, load_jobs, save_jobs, start_job


def wait_for_job(job_id, job_file, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = get_job(job_id, job_file)
        if job and job.get("status") in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.1)
    raise AssertionError(f"job did not finish: {job_id}")


def main() -> int:
    root = project_path("data/temp") / f"job_runner_{uuid.uuid4().hex[:8]}"
    job_file = root / "jobs.json"
    try:
        root.mkdir(parents=True, exist_ok=True)
        try:
            start_job("unknown_command", job_file=job_file)
            raise AssertionError("unknown command should be rejected")
        except ValueError as exc:
            assert "Unsupported operator action" in str(exc)

        job = start_job("detect_outputs", job_file=job_file)
        assert job["job_type"] == "detect_outputs"
        assert job["command"].startswith("py tools\\detect_videoautopipeline_outputs.py")
        finished = wait_for_job(job["job_id"], job_file)
        assert finished["status"] in {"completed", "failed"}
        assert finished["args"][0] == sys.executable
        assert load_jobs(job_file)["jobs"]
        assert list_jobs(job_file=job_file)

        stale_job_file = root / "stale_jobs.json"
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
                        "pid": 99999999,
                        "cancellable": False,
                    }
                ],
            },
            stale_job_file,
        )
        reconciled = get_job("stale", stale_job_file)
        assert reconciled["status"] == "failed"
        assert "captured output" in reconciled["stderr_tail"]
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("test_job_runner: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
