from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.replace_diagnostics import replace_diagnostics, summary_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize Plato safe replace logs.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--log", help=r"Path to replace_log.json, for example logs\replace_log.json.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = replace_diagnostics(args.log)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(summary_text(payload))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
