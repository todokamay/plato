from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KEY_ROUTES = ["/", "/control-center", "/health", "/api/status", "/api/health"]


def run_command(label: str, args: list[str], *, required: bool = True) -> dict:
    completed = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part).strip()
    status = "PASS" if completed.returncode == 0 else ("FAIL" if required else "WARN")
    return {"label": label, "status": status, "returncode": completed.returncode, "output": output}


def check_routes(server_url: str) -> list[dict]:
    results = []
    for route in KEY_ROUTES:
        url = server_url.rstrip("/") + route
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                results.append({"label": route, "status": "PASS", "code": response.status})
        except urllib.error.URLError as exc:
            results.append({"label": route, "status": "SKIP", "error": str(exc)})
    return results


def print_summary(results: list[dict], routes: list[dict]) -> None:
    print("Smoke Factory Run")
    for item in results:
        print(f"{item['status']} {item['label']} rc={item['returncode']}")
        if item["status"] == "FAIL" and item.get("output"):
            print(item["output"])
    print("Routes")
    for item in routes:
        if item["status"] == "PASS":
            print(f"PASS {item['label']} {item['code']}")
        else:
            print(f"SKIP {item['label']} - server not reachable")
    passed = sum(1 for item in results if item["status"] == "PASS")
    failed = sum(1 for item in results if item["status"] == "FAIL")
    skipped_routes = sum(1 for item in routes if item["status"] == "SKIP")
    print()
    print("Summary")
    print(f"  checks_passed: {passed}")
    print(f"  checks_failed: {failed}")
    print(f"  routes_skipped: {skipped_routes}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local smoke validation for Plato Factory OS.")
    parser.add_argument("--server-url", default="http://127.0.0.1:8000", help="Already-running Plato server URL for route checks.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip the full test runner for a faster smoke check.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results = [
        run_command("compile", [sys.executable, "-m", "compileall", "app.py", "modules", "tools"]),
    ]
    if not args.skip_tests:
        results.append(run_command("tests", [sys.executable, "tools/run_tests.py"]))
    results.extend(
        [
            run_command("orchestrator status", [sys.executable, "tools/run_orchestrator.py", "--status-only", "--json"]),
            run_command("detector", [sys.executable, "tools/detect_videoautopipeline_outputs.py", "--json"]),
        ]
    )
    routes = check_routes(args.server_url)
    payload = {"results": results, "routes": routes}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_summary(results, routes)
    return 1 if any(item["status"] == "FAIL" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
