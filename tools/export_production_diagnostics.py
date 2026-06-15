from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.production_diagnostics import diagnostics_summary_text, export_production_diagnostics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a sanitized Plato production diagnostics snapshot.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--output-dir", default="data/diagnostics", help=r"Base output directory. Default: data\diagnostics.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = export_production_diagnostics(args.output_dir)
    if args.json:
        print(json.dumps({k: v for k, v in payload.items() if k != "snapshot"}, ensure_ascii=False, indent=2))
    else:
        print(diagnostics_summary_text(payload["snapshot"]))
        print(f"output_dir: {payload['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
