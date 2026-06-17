import shutil
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import project_path
from modules import job_runner


def wait_for_job(job_id, job_file, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = job_runner.get_job(job_id, job_file)
        if job and job.get("status") in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.1)
    raise AssertionError(f"job did not finish: {job_id}")


def main() -> int:
    root = project_path("data/temp") / f"job_runner_encoding_{uuid.uuid4().hex[:8]}"
    job_file = root / "jobs.json"
    action = f"encoding_test_{uuid.uuid4().hex}"
    try:
        root.mkdir(parents=True, exist_ok=True)
        script = root / "unicode_child.py"
        script.write_text(
            "import os, sys\n"
            "assert os.environ.get('PYTHONUTF8') == '1'\n"
            "assert os.environ.get('PYTHONIOENCODING') == 'utf-8'\n"
            "text = '✓\\nemoji 😀\\nрусский\\n“unicode quotes”\\n'\n"
            "sys.stdout.buffer.write(text.encode('utf-8'))\n"
            "sys.stdout.flush()\n",
            encoding="utf-8",
        )
        job_runner.ACTION_DEFINITIONS[action] = {
            "display": "py unicode_child.py",
            "args": [str(script)],
            "requires_folder": False,
            "cancellable": False,
        }
        job = job_runner.start_job(action, job_file=job_file)
        finished = wait_for_job(job["job_id"], job_file)
        output = finished.get("stdout_tail") or ""
        assert finished["status"] == "completed", finished
        assert "✓" in output
        assert "emoji 😀" in output
        assert "русский" in output
        assert "“unicode quotes”" in output
        assert "UnicodeDecodeError" not in (finished.get("stderr_tail") or "")
    finally:
        job_runner.ACTION_DEFINITIONS.pop(action, None)
        shutil.rmtree(root, ignore_errors=True)

    print("test_job_runner_encoding: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
