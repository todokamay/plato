from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OPTIONAL_IMPORTS = {
    "fastapi": "FastAPI is not installed in this environment.",
    "uvicorn": "Uvicorn is not installed in this environment.",
    "cv2": "OpenCV/cv2 is not installed in this environment.",
    "opencv": "OpenCV is not installed in this environment.",
}


def _optional_import_error(output: str) -> str | None:
    lowered = output.lower()
    for name, reason in OPTIONAL_IMPORTS.items():
        patterns = [
            rf"modulenotfounderror: no module named ['\"]{re.escape(name)}['\"]",
            rf"importerror: .*{re.escape(name)}",
            rf"dll load failed while importing {re.escape(name)}",
        ]
        if any(re.search(pattern, lowered, flags=re.DOTALL) for pattern in patterns):
            return reason
    return None


def _run_test(path: Path) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        env=env,
    )
    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
    optional_reason = None if completed.returncode == 0 else _optional_import_error(output)
    if completed.returncode == 0:
        status = "PASS"
    elif optional_reason:
        status = "SKIP"
    else:
        status = "FAIL"
    return {
        "path": path,
        "status": status,
        "returncode": completed.returncode,
        "output": output.strip(),
        "reason": optional_reason,
    }


def main() -> int:
    tests = sorted((ROOT / "tools").glob("test_*.py"))
    if not tests:
        print("No tests found.")
        return 1

    results = []
    for test in tests:
        result = _run_test(test)
        results.append(result)
        label = test.relative_to(ROOT)
        if result["status"] == "PASS":
            print(f"PASS {label}")
        elif result["status"] == "SKIP":
            print(f"SKIP {label} - env-only: {result['reason']}")
        else:
            print(f"FAIL {label}")
            if result["output"]:
                print(result["output"])

    passed = sum(1 for item in results if item["status"] == "PASS")
    skipped = sum(1 for item in results if item["status"] == "SKIP")
    failed = [item for item in results if item["status"] == "FAIL"]

    print()
    print("Summary")
    print(f"  total:   {len(results)}")
    print(f"  passed:  {passed}")
    print(f"  skipped: {skipped}")
    print(f"  failed:  {len(failed)}")

    if failed:
        print()
        print("Real failures:")
        for item in failed:
            print(f"  {item['path'].relative_to(ROOT)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
