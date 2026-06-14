from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_step(label: str, args: list[str]) -> dict:
    completed = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part).strip()
    status = "PASS" if completed.returncode == 0 else "FAIL"
    print(f"{status} {label}")
    if output and completed.returncode != 0:
        print(output)
    return {"label": label, "status": status, "returncode": completed.returncode, "output": output}


def main() -> int:
    (ROOT / "data" / "temp").mkdir(parents=True, exist_ok=True)
    steps = [
        ("compile", [sys.executable, "-m", "compileall", "app.py", "modules", "tools"]),
        ("unit", [sys.executable, "tools/run_tests.py"]),
        ("orchestrator", [sys.executable, "tools/run_orchestrator.py", "--once", "--json"]),
        ("watch", [sys.executable, "tools/watch_videoautopipeline_outputs.py", "data/temp", "--once", "--dry-run", "--stable-seconds", "0", "--json"]),
    ]
    results = [run_step(label, args) for label, args in steps]
    failed = [item for item in results if item["status"] == "FAIL"]
    print()
    print("Full Validation Summary")
    print(f"  total:  {len(results)}")
    print(f"  passed: {len(results) - len(failed)}")
    print(f"  failed: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
