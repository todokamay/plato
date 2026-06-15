from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.decision_explainer import explain_from_file, format_explanation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Explain a clip decision from a Plato run summary.")
    parser.add_argument("summary", help="Path to run_summary.json or run_summary.csv.")
    parser.add_argument("--clip", required=True, help="Clip filename to explain.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = explain_from_file(args.summary, args.clip)
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else f"ERROR: {exc}")
        return 1
    payload = {"ok": True, **payload}
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else format_explanation(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
