from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str]) -> int:
    return subprocess.run(args, cwd=ROOT).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Plato release helper.")
    parser.add_argument("action", choices=["validate", "build", "tag", "archive"], help="Release action.")
    parser.add_argument("--tag", default="v1.0.0", help="Tag name for tag action.")
    args = parser.parse_args()

    if args.action == "validate":
        return run([sys.executable, "tools/run_full_validation.py"])
    if args.action == "build":
        return run([sys.executable, "-m", "compileall", "app.py", "modules", "tools"])
    if args.action == "tag":
        return run(["git", "tag", args.tag])
    if args.action == "archive":
        archive_dir = ROOT / "data" / "release_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        print(f"archive_dir: {archive_dir}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
