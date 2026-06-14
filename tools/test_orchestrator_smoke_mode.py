import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_cmd(args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main() -> int:
    status = run_cmd([sys.executable, "tools/run_orchestrator.py", "--status-only"])
    assert status.returncode == 0, status.stderr
    assert "orchestrator_state:" in status.stdout
    assert "Traceback" not in status.stdout + status.stderr

    dry = run_cmd([sys.executable, "tools/run_orchestrator.py", "--once", "--dry-run"])
    assert dry.returncode == 0, dry.stderr
    assert "dry_run: True" in dry.stdout
    assert "Traceback" not in dry.stdout + dry.stderr

    missing_root = ROOT / "data" / "temp" / "missing_vap_root_for_test"
    missing = run_cmd(
        [
            sys.executable,
            "tools/run_orchestrator.py",
            "--status-only",
            "--detect-videoautopipeline-outputs",
            "--videoautopipeline-root",
            str(missing_root),
        ]
    )
    output = missing.stdout + missing.stderr
    assert missing.returncode == 0
    assert "detector_found: False" in output
    assert "Suggested next command" in output
    assert "Traceback" not in output

    print("test_orchestrator_smoke_mode: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
