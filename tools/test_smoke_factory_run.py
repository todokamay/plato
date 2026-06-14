import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    completed = subprocess.run(
        [sys.executable, "tools/smoke_factory_run.py", "--skip-tests", "--server-url", "http://127.0.0.1:9"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert "Smoke Factory Run" in output
    assert "PASS compile" in output
    assert "PASS orchestrator status" in output
    assert "PASS detector" in output
    assert "routes_skipped:" in output
    assert "Traceback" not in output
    print("test_smoke_factory_run: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
