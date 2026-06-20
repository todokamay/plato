from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.final_cleanup import cleanup_after_delivery


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely clean intermediates after a successful Plato delivery.")
    parser.add_argument("delivery_summary", help="Path to delivery_summary.json.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-final-only", action="store_true")
    parser.add_argument("--confirm-cleanup", action="store_true")
    parser.add_argument("--allow-source-delete", action="store_true")
    parser.add_argument("--cleanup-reports", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = "keep_final_only" if args.keep_final_only else "dry_run"
    if args.dry_run:
        mode = "dry_run"
    result = cleanup_after_delivery(
        args.delivery_summary,
        mode=mode,
        confirm=args.confirm_cleanup,
        allow_source_delete=args.allow_source_delete,
        cleanup_reports=args.cleanup_reports,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
