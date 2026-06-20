from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.instagram_publisher import get_next_queue_item, publish_one_dry_run
from modules.instagram_queue import QUEUE_FILE, load_queue


def _print(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(payload.get("reason") or payload.get("status") or payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run one Plato Instagram queue item.")
    parser.add_argument("--queue", default=str(QUEUE_FILE))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-safe-to-test", action="store_true")
    parser.add_argument("--peek", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.peek:
        item = get_next_queue_item(load_queue(args.queue))
        _print({"ok": True, "item": item, "reason": "next queued item" if item else "no queued items"}, args.json)
        return 0

    if not args.dry_run:
        _print({"ok": False, "reason": "Real Instagram publishing is not implemented in v1.3.1. Use --dry-run."}, args.json)
        return 1

    try:
        result = publish_one_dry_run(args.queue, allow_safe_to_test=args.allow_safe_to_test)
    except Exception as exc:
        _print({"ok": False, "dry_run": True, "published": False, "status": "failed", "reason": str(exc)}, args.json)
        return 1
    _print(result, args.json)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
